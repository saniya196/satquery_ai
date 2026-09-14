# SatQuery AI — Review 1 Documentation
**SIH Problem Statement ID:** SIH26167

---

## 1. Motivation of the Theme and Title

Satellite remote-sensing data is now produced at a scale that far exceeds the ability of non-experts to interpret it. Missions like Sentinel-2 generate global multispectral coverage every few days, yet extracting actionable insight from this imagery — identifying land cover, assessing vegetation health, detecting water bodies — still requires specialized GIS training. Stakeholders who most need this information (agriculture officers, disaster response teams, urban planners) often lack that expertise. SatQuery AI addresses this gap by allowing a user to ask natural-language questions about a satellite image and receive an answer that is transparently grounded in real, computed remote-sensing measurements — not a generic AI-generated guess.

## 2. Problem Statement

**SIH26167 — SatQuery AI: An Interactive Vision-Language Assistant for Multimodal Remote Sensing Image Analysis through Text Queries.** Build a system that accepts satellite/remote-sensing imagery and natural-language queries, and returns answers grounded in the actual image content — ultimately across optical, SAR, and multitemporal modalities.

**Phase 1 scope (this review):** the sub-problem of building a grounded, evidence-based visual question-answering system for optical/multispectral (Sentinel-2) imagery, establishing the modular foundation that later phases extend to SAR, change detection, and retrieval-augmented explanation.

## 3. Abstract

SatQuery AI is a vision-language assistant for satellite image analysis, developed over a one-year Software Engineering project. Phase 1 (this review) implements a complete, working pipeline: a fine-tuned CNN classifies land cover from Sentinel-2 imagery (EuroSAT dataset, **92–93% validation accuracy**), spectral indices (NDVI, NDWI) are computed directly from the image's 13 spectral bands, and a grounded answer-composition layer converts these computed values into natural-language responses — with every answer explicitly tied to a specific numeric value, never generated from raw pixels by a language model. The system also visually highlights the image region most relevant to each answer and logs a query history. Later phases (Reviews 2–3 and Final) will extend this foundation to SAR imagery, multitemporal change detection, and retrieval-augmented domain knowledge, without requiring a rewrite of the Phase 1 architecture.

## 4. Existing System

Generic vision-language chatbots (e.g. GPT-4V, Gemini) can describe the visual content of a satellite image, but cannot compute domain-specific quantitative metrics like NDVI, cannot process SAR or multispectral band data (they only see rendered RGB pixels), and provide no verifiable evidence for their claims. Dedicated GIS platforms (QGIS, Google Earth Engine) support this kind of quantitative analysis but require expert operation and offer no natural-language interface — there is no system that combines domain-correct remote-sensing computation with an accessible conversational interface.

## 5. Proposed Solution

SatQuery AI separates *computation* from *language*: a preprocessing and classification pipeline performs verifiable remote-sensing analysis (band extraction, NDVI/NDWI computation, land-cover classification), and a lightweight answer-composition layer converts only the *results* of that analysis into natural language. This guarantees every claim in an answer is traceable to a real computed number, and keeps the architecture modular so that later modalities (SAR, multitemporal) can be added without redesigning the core system.

## 6. Features (Review 1) — Measurable and Demonstrable

| # | Feature | Measurable outcome |
|---|---|---|
| 1 | Grounded natural-language querying | User submits image + question, receives an answer explicitly referencing computed values (demonstrated live) |
| 2 | Land-cover classification | ResNet18 fine-tuned on EuroSAT — **92–93% validation accuracy** (reported per epoch) |
| 3 | Spectral index computation (NDVI, NDWI) | Computed from real 13-band Sentinel-2 data; verified directionally correct — AnnualCrop NDVI = **+0.189** (vegetation-positive), SeaLake NDVI = **−0.295** (water-negative), SeaLake NDWI = **+0.529** (water-positive) |
| 4 | Evidence region highlighting | System returns pixel-coordinate bounding box of the most relevant 16×16 image cell, rendered as an overlay in the UI |
| 5 | Confidence scoring | Classifier softmax probability shown with every answer (e.g. 99.0%, 99.7% on test samples) |
| 6 | Query history | Every query, answer, and computed evidence persisted (SQLite) and retrievable via API/UI |

## 7. System Architecture

```
React frontend (upload, query input, evidence overlay, history view)
        ↓ HTTP (multipart form)
FastAPI backend
        ↓
Preprocessing module (band extraction, NDVI/NDWI computation) — ml/src/preprocessing.py
        ↓
Land-cover classifier (ResNet18, fine-tuned on EuroSAT) — backend/model_utils.py
        ↓
Grid-based evidence region selector
        ↓
Template-based answer composition (consumes only computed values, never raw pixels)
        ↓
SQLite history store
```

Deferred to later reviews (architecture already accommodates these without redesign): SAR preprocessing module, change-detection module, RAG/vector knowledge base, geospatial reasoning engine, fine-tuned domain VLM.

## 8. Technology Stack

- **Frontend:** React (Vite), Axios
- **Backend:** FastAPI (Python)
- **AI/ML:** PyTorch, torchvision (ResNet18 transfer learning), rasterio (band I/O)
- **Storage:** SQLite (query history)
- **Version control:** Git/GitHub

Chosen to keep the entire stack in Python end-to-end for the AI-serving layer, minimizing backend-integration overhead so effort stays focused on the remote-sensing/AI pipeline itself rather than cross-language service plumbing.

## 9. Dataset

**EuroSAT** (Helber et al., 2019) — 27,000 labeled, geo-referenced Sentinel-2 image patches across 10 land-cover classes, with all 13 spectral bands available per image. Used both the RGB subset (classifier training) and the full 13-band GeoTIFF subset (NDVI/NDWI computation, since spectral index calculation requires the near-infrared band not present in RGB-only imagery). Selected for its small size, labeled ground truth (enabling a reportable accuracy metric), and genuine multispectral band availability — critical for the project's "not just an LLM wrapper" positioning, since NDVI is computed from real sensor data, not simulated.

## 10. 30% Implementation — What Is Actually Working

- Reusable preprocessing module: band extraction, NDVI computation, NDWI computation (tested and verified against known vegetation/water spectral signatures)
- Fine-tuned ResNet18 classifier: 92–93% validation accuracy on EuroSAT
- FastAPI backend with three working endpoints: `/analyze` (classification + indices), `/query` (grounded answer + evidence region), `/history` (query log retrieval)
- Grid-based evidence region highlighting, tied to whichever index (NDVI/NDWI) is relevant to the answer
- SQLite-backed query history, tested with multiple logged entries
- React frontend: file upload, question input, live results display (answer, confidence, index values, evidence overlay), history view
- End-to-end tested on two distinct classes (AnnualCrop, SeaLake) with correct, distinguishable results in both cases

**Explicitly not implemented yet (by design):** SAR imagery support, multi-image change detection, multitemporal analysis, RAG/domain knowledge retrieval, geospatial coordinate reasoning, fine-tuned vision-language model. These form the roadmap for Reviews 2–3 and Final, building directly on this phase's modular pipeline.

## 11. References

1. Helber, P., Bischke, B., Dengel, A., & Borth, D. (2019). EuroSAT: A Novel Dataset and Deep Learning Benchmark for Land Use and Land Cover Classification. *IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing.*
2. Rouse, J.W. et al. (1974). Monitoring vegetation systems in the Great Plains with ERTS. (NDVI foundational reference.)
3. McFeeters, S.K. (1996). The use of the Normalized Difference Water Index (NDWI) in the delineation of open water features. *International Journal of Remote Sensing.*
4. Lobry, S. et al. RSVQA: Visual Question Answering for Remote Sensing Data. (Reference for VQA-for-remote-sensing task framing.)
5. Copernicus Sentinel-2 Mission Documentation, European Space Agency.
6. EuroSAT Dataset, GitHub: https://github.com/phelber/eurosat

---

*Screenshots of the working UI (upload → answer → evidence overlay → history) should be inserted alongside Sections 6 and 10 in the final submitted version.*
