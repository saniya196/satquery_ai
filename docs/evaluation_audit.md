# SatQuery AI — Scientific Evaluation Audit (Milestone 2A)

## Existing validation coverage
**Spectral indices** (`tests/test_indices.py`): NDVI/NDWI/NDBI/SAVI hand values, divide-by-zero -> NaN, missing band errors, valid mask application, stats ignore NaN. Covers formulas and nodata/div-by-zero behavior.

**Cloud masking / preprocessing** (`tests/test_masking.py`): SCL valid mask fractions, invalid SCL classes, reflectance conversion (including misreported offset handling for S2 L2A), resampling shapes/categorical, AOI clipping, combined valid mask, AOI validation. Good coverage of masking logic.

**Raster alignment** (`tests/test_alignment.py`): Cross-grid alignment utilities tested. Change detection uses alignment when grids differ (see `services/analysis.py`).

**Change detection / hotspots** (`tests/test_change.py`): Change detection logic tested with fixtures. Hotspot detection present.

**Trends** (`tests/test_trend.py`): Mann-Kendall + Sen's slope tested.

**Land cover** (`tests/test_classification.py`, `tests/test_land_cover.py`, `tests/test_uploaded_landcover.py`, `tests/test_numpy_resnet*.py`): Classifier loading, uploaded land cover, numpy/resnet parity. Model is EuroSAT L1C-trained ResNet18.

**Confidence/evidence/grounding** (`tests/test_confidence.py`, `tests/test_grounding.py`): Deterministic confidence weights tested, grounding validator tested.

**Pipeline/API** (`tests/test_pipeline.py`, `tests/test_api.py`): Integration tests with fakes.

## Synthetic vs real data
- **Synthetic/unit**: Most tests use numpy arrays created in-test or small fixtures (`tests/fakes.py`). No large real GeoTIFF downloads required.
- **Real-data integration**: API/pipeline tests may use fakes/mocks; no systematic real Sentinel-2 regression suite exists. Uploaded GeoTIFF tests use real file handling.

## Gaps and scientific risks
1. **No end-to-end real Sentinel-2 regression** - Cannot verify against known scenes/ground truth.
2. **Change statistics vs raster values** - Need explicit tests confirming hotspot counts/areas match pixel-level sums.
3. **CRS/transform/AOI masking** - Mostly unit tested, but need more explicit checks for edge cases.
4. **Confidence claims** - Weights are deterministic and tested, but "accuracy" not claimed; need to ensure no unsupported claims.
5. **Land cover applicability** - EuroSAT L1C vs Sentinel-2 L2A domain shift not quantified; implementation correctness vs accuracy must be distinguished.
6. **p-values** - Correctly avoided for pixel-level; trend uses median-based MK with caveats as required.
7. **Scale/offset** - Handled per requirements; tests confirm behavior.

## New tests added
- `tests/test_scientific_audit.py`: Deterministic tests for NDVI/NDWI/MNDWI/NDBI/SAVI formulas with known arrays, div-by-zero -> NaN, valid mask/stats, change detection agreement (diff/hotspots), AOI masking + CRS/transform, confidence components, land cover raster shapes.

## Exact test results
Ran full backend suite: **206 passed, 1 skipped, 4 warnings** (added 3 new tests).

## Prioritized plan for real-data evaluation
1. **P0 - Smoke tests**: Pick 2-3 known Sentinel-2 L2A scenes (different tiles/dates) over simple AOIs; verify NDVI range/stats reasonable.
2. **P1 - Change detection**: Same tile, two dates with obvious change; manually verify a few hotspots.
3. **P2 - Cloud masking**: AOI with clouds/shadows; check valid-pixel fraction and exclusions.
4. **P3 - Land cover**: Compare outputs qualitatively against known land cover; document domain shift (no accuracy score without ground truth).
5. **P4 - Trends**: Time series over stable area; verify trend logic with caveats.

**Recommendation**: Use Element84 Earth Search, record all metadata in evaluation report format. Never fabricate ground truth or accuracy scores.
