# SatQuery AI — ML Classification Strategy

## 1. Model Choice: EuroSAT-Trained ResNet18

### 1.1 Why This Model

| Factor | Decision |
|---|---|
| **Dataset** | EuroSAT — 27,000 labelled 64×64 Sentinel-2 patches across 10 land-use classes. It is the standard benchmark for Sentinel-2 classification. |
| **Architecture** | ResNet18 — small enough for CPU inference (11.7M params), well-understood, good transfer-learning base. |
| **Published accuracy** | ~98% on EuroSAT test split (RGB), ~99% on 13-band. This is a ceiling we will not reach in production. |
| **Alternatives considered** | ResNet50 (larger, marginal gain), Vision Transformer (needs more data), Random Forest on handcrafted features (lower accuracy, less transferable). |

### 1.2 Input Specification

| Property | Value |
|---|---|
| Input size | 64 × 64 pixels |
| Channels | 13 bands (full Sentinel-2 L2A) ideal; 4-band (B02, B03, B04, B08) minimum fallback |
| Normalisation | Per-band mean/std from EuroSAT training set |
| Resolution | 10m (bands at 20m/60m are resampled via bilinear interpolation to 10m) |

### 1.3 Patch Strategy

The model processes 64×64-pixel patches. For an AOI:

1. **Tile the AOI** into a grid of 256×256-pixel tiles (as done for all operations)
2. **Subdivide each tile** into 16 non-overlapping 64×64 patches
3. **Classify each patch** independently
4. **Reassemble** patch predictions into a full AOI classification map

```
AOI (e.g. 5120 × 5120 px)
  └── 400 tiles (256 × 256)
       └── 6400 patches (64 × 64)
            └── 6400 predictions
```

For border patches that are partially outside the AOI, we classify the full patch and mask out-of-AOI pixels in the result.

---

## 2. EuroSAT Classes → Product Classes

### 2.1 Mapping

EuroSAT has 10 classes. Our product collapses them into 5 user-facing categories:

| EuroSAT Class | Product Category | Collapse Rationale |
|---|---|---|
| AnnualCrop | **Agriculture** | Users care about "farmland", not crop rotation type |
| PermanentCrop | **Agriculture** | |
| Pasture | **Grassland** | |
| HerbaceousVegetation | **Grassland** | Distinction is ecologically fine-grained; not actionable for most users |
| Forest | **Forest** | Kept as-is |
| River | **Water** | |
| SeaLake | **Water** | Users care about water presence, not water body type |
| Industrial | **Built-up** | |
| Residential | **Built-up** | |
| Highway | **Built-up** | All three are "developed land" |

### 2.2 Output Format

For each patch:
```json
{
  "class_10": "AnnualCrop",
  "class_5": "Agriculture",
  "confidence": 0.87,
  "top3": [
    { "class": "AnnualCrop", "prob": 0.87 },
    { "class": "PermanentCrop", "prob": 0.08 },
    { "class": "Pasture", "prob": 0.03 }
  ]
}
```

Aggregated for the full AOI:
```json
{
  "class_distribution": {
    "Agriculture": { "pct": 42.3, "area_km2": 18.5 },
    "Forest": { "pct": 28.1, "area_km2": 12.3 },
    "Water": { "pct": 12.0, "area_km2": 5.2 },
    "Grassland": { "pct": 10.6, "area_km2": 4.6 },
    "Built-up": { "pct": 7.0, "area_km2": 3.1 }
  },
  "mean_confidence": 0.76,
  "low_confidence_pct": 15.2,
  "total_patches": 6400
}
```

---

## 3. Inference Pipeline

```mermaid
flowchart LR
    A[AOI GeoTIFF] --> B[Tile into 256x256]
    B --> C[Subdivide into 64x64 patches]
    C --> D[Normalise per-band]
    D --> E[ResNet18 forward pass<br/>batch_size=64]
    E --> F[Softmax → 10-class probs]
    F --> G[Map to 5 product classes]
    G --> H[Reassemble classification raster]
    H --> I[Compute aggregate stats]
    I --> J[Generate confidence heatmap]
```

### 3.1 Performance Estimates

| AOI Size | Patches | CPU Time (est.) | GPU Time (est.) |
|---|---|---|---|
| 1 km² | ~100 | ~2s | <0.5s |
| 10 km² | ~1,000 | ~20s | ~3s |
| 50 km² | ~5,000 | ~100s | ~12s |
| 100 km² (max) | ~10,000 | ~200s | ~25s |

CPU inference is acceptable for MVP. GPU is recommended if processing > 50 km² becomes common.

### 3.2 Model Loading

- Model weights stored as `models/eurosat_resnet18.pt` (PyTorch state dict, ~45 MB)
- Loaded once at server startup, held in memory
- Thread-safe inference via `torch.no_grad()` context

---

## 4. Honest Limitations

> [!IMPORTANT]
> This section is mandatory reading. We must communicate these limitations to users, not hide them.

### 4.1 Domain Shift

**Problem:** EuroSAT was trained predominantly on European landscapes. Indian terrain — arid regions, monsoon-affected areas, tropical forests, informal settlements — may not match the training distribution.

**Symptoms:**
- Reduced accuracy on Indian AOIs (estimated 10–25% drop for some classes)
- Confusion between `Pasture` and `AnnualCrop` in semi-arid regions
- `Residential` vs `Industrial` confusion in dense Indian cities

**Mitigation:**
- Always show confidence scores; flag patches with confidence < 0.6
- Document expected accuracy ranges per region (post-evaluation)
- Plan for fine-tuning on Indian data in Phase 6 (collect 2,000+ labelled patches)

### 4.2 Temporal Mismatch

**Problem:** EuroSAT images are from a specific time period. Sentinel-2 data from different seasons or years may have different spectral characteristics (atmospheric conditions, sun angle, phenology).

**Mitigation:**
- Use L2A (atmospherically corrected) products only
- Seasonal accuracy will vary — monsoon cloud cover degrades everything

### 4.3 Resolution Limits

**Problem:** At 10m resolution, a 64×64 patch covers 640m × 640m. This is too coarse for:
- Individual buildings
- Narrow rivers (< 30m wide)
- Small farm plots (< 0.5 ha)
- Mixed-use areas (e.g., houses mixed with farmland)

**Mitigation:**
- Acknowledge in the UI: "Classification is approximate at ~640m resolution per patch"
- Mixed patches will get the dominant class — display confidence to signal heterogeneity

### 4.4 Class Coverage Gaps

**Problem:** EuroSAT does not have classes for:
- Desert / barren land
- Wetlands / marshes
- Snow / ice
- Cloud / cloud shadow (these should be masked, not classified)

**Mitigation:**
- Pre-mask clouds using the Sentinel-2 SCL (Scene Classification Layer) band
- Patches that are >50% masked are excluded from classification
- Barren/desert areas will likely be classified as `Pasture` or `AnnualCrop` with low confidence — flag these

### 4.5 Not a Ground-Truth Substitute

**Statement for users:**

> *"SatQuery AI's land-use classification uses a machine learning model trained on satellite imagery. It provides estimates, not ground-truth measurements. Results should be validated against field data for any decision-making purpose. Confidence scores indicate model certainty — low confidence means the model is unsure."*

---

## 5. Evaluation Plan

### 5.1 Metrics

| Metric | How measured | Target (EuroSAT test) | Target (Indian AOIs) |
|---|---|---|---|
| Overall accuracy (10-class) | Correct / Total patches | ≥ 92% | ≥ 75% |
| Overall accuracy (5-class) | Correct / Total patches | ≥ 95% | ≥ 82% |
| Per-class F1 (10-class) | Precision × Recall harmonic mean | ≥ 0.85 per class | ≥ 0.65 per class |
| Confidence calibration | ECE (Expected Calibration Error) | ≤ 0.05 | ≤ 0.10 |

### 5.2 Evaluation Dataset

1. **EuroSAT test split** (2,700 patches): Verify our model reproduces published accuracy
2. **Indian validation set** (target: 500 patches across 5 regions):
   - Manually labelled using Google Earth high-res imagery as reference
   - Regions: Delhi NCR, Varanasi, Rajasthan desert fringe, Kerala coast, Pune suburbs
   - Balanced across 5 product classes
   - Created during Phase 6 (ML integration)

### 5.3 Confidence Thresholding

We'll evaluate accuracy at different confidence thresholds:

| Confidence Threshold | % Patches Classified | Expected Accuracy |
|---|---|---|
| 0.0 (all) | 100% | Baseline |
| 0.5 | ~90% | Baseline + 3–5% |
| 0.6 (default) | ~80% | Baseline + 5–8% |
| 0.8 | ~60% | Baseline + 10–15% |

Users can choose their threshold. Default is 0.6 — patches below this are shown as "uncertain" in a separate colour.

---

## 6. Future Model Improvements

| Improvement | Phase | Effort |
|---|---|---|
| Fine-tune on Indian labelled data (2k+ patches) | Phase 6 | 2–3 weeks |
| Add barren/desert class | Phase 7 | Needs training data collection |
| Ensemble with Random Forest on indices (NDVI, NDWI, NDBI) | Phase 7 | 1 week |
| Upgrade to EfficientNet or ViT-Small | Phase 8 | 2 weeks, needs GPU eval |
| Multi-temporal classification (stack 3 dates) | Phase 8 | Research-grade effort |
