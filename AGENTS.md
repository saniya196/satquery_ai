# SatQuery AI (SIH26167) - Project Rules

## What this is
A natural-language satellite intelligence platform. User draws an AOI, asks a question,
the system turns it into a structured query, runs deterministic analysis on real Sentinel-2
pixels, and returns an evidence-backed, validated explanation.

Pipeline: question -> structured query -> validation -> data retrieval -> preprocessing
-> index/change/ML analysis -> evidence + confidence -> grounded explanation -> dashboard.

## Current state
backend/ already has working, tested modules: indices, preprocessing, change_detection,
statistics (Mann-Kendall + Sen's slope implemented in-house), evidence/confidence,
validation/grounding, query_engine, satellite provider, rendering/geo, services/analysis, api.
All tests pass (python -m pytest -q from backend/). EXTEND these modules. Do not rewrite,
restructure or re-scaffold them.

## Non-negotiables
1. The LLM interprets questions and phrases explanations. It NEVER computes or invents
   numbers, dates, metadata, or predictions.
2. No fabricated data. Real Sentinel-2 imagery only. Synthetic rasters are allowed ONLY
   inside tests and must be labelled synthetic.
3. No hard-coded demo answers, fake accuracy, or fake confidence scores.
4. Every analysis result carries an Evidence object: source, item IDs, dates, bands,
   formula, AOI, preprocessing steps, valid-pixel %, thresholds, numeric results, model info.
5. If data is missing, cloudy, or the query is ambiguous, ask or fail clearly. Never guess.
6. One coherent platform. Do not add features that don't connect to the main pipeline.

## Fixed stack (do not swap without asking me)
- Backend: Python 3.13 (local), FastAPI, Pydantic v2, numpy, scipy, shapely, affine,
  pystac-client, scikit-learn, pytest. rasterio is used ONLY inside
  backend/app/satellite/provider.py. Do NOT add pyproj, geopandas or pymannkendall.
- This laptop blocks some compiled libraries (rasterio, pyproj). Use
  backend/app/rendering/geo.py (bounds_wgs84) for coordinate conversion. Before adding any
  new dependency, check it imports on this machine, and ask me first.
- Data: Sentinel-2 L2A via STAC (Element84 Earth Search, no key needed; Microsoft Planetary
  Computer as fallback). Read COGs with windowed reads over the AOI only.
  Hide the provider behind a `SatelliteProvider` interface.
- DB: SQLite via SQLAlchemy now. Keep the schema Postgres/PostGIS-compatible for later.
- Cache: disk cache keyed by (item_id, band, aoi_hash). No Redis yet.
- Jobs: FastAPI BackgroundTasks + in-memory job dict now (queued/processing/completed/failed);
  move to a SQLite jobs table in the history phase. No Celery.
- ML: PyTorch + torchvision ResNet18 fine-tuned on EuroSAT (multispectral). Training happens
  in a Colab notebook under `notebooks/`; the app only loads weights from `models/`.
- LLM: behind an `LLMClient` interface. Default provider via env var. A rule-based fallback
  parser must work with no API key.
- Frontend: React + Vite + TypeScript, Leaflet + leaflet-draw, Recharts.
- Docker Compose only at the final phase. Dev runs natively on Windows in CMD (cmd.exe):
  give CMD commands, not PowerShell.

## Remote-sensing rules
- Apply reflectance scale/offset from product metadata. Do not hard-code it blindly.
- NDVI = (B08-B04)/(B08+B04). NDWI (McFeeters) = (B03-B08)/(B03+B08).
  MNDWI = (B03-B11)/(B03+B11). NDBI = (B11-B08)/(B11+B08). SAVI = ((B08-B04)/(B08+B04+L))*(1+L), L=0.5.
- B11 is 20 m: resample to the 10 m grid (bilinear for bands, nearest for SCL).
- Valid-pixel mask from SCL. Exclude no-data, saturated, cloud shadow, medium/high cloud,
  cirrus, snow.
- Divide-by-zero becomes nodata, never 0.
- Refuse analysis below a configurable valid-pixel threshold.

## Statistics honesty
- Do NOT report p-values from pixel-level tests (spatial autocorrelation makes them invalid).
- Trend: Mann-Kendall + Sen's slope (backend/app/statistics/trend.py) on per-date AOI medians.
  Require >= 8 valid dates and state the seasonality caveat. "Decreased" and
  "significantly decreasing trend" are different claims; the code decides which wording is
  allowed, not the LLM.
- Change classes (significant/moderate decrease, stable, ...) use configurable thresholds
  that are shown in the UI.

## Confidence / data-quality score
Deterministic and reproducible. Weights live in config, are documented in
docs/confidence.md, and are unit-tested. Inputs: valid-pixel %, cloud cover, temporal
separation, data availability, model confidence (if ML), statistical support (if relevant).

## Grounded response validator
The LLM receives only the structured result. Extract every number/date in its answer and
check each against the result object (with rounding tolerance). Mismatch -> regenerate
(max 2 tries) -> fall back to a deterministic template answer.

## Working style
- Plan first, then code. Per phase: plan -> implement -> tests -> run it -> walkthrough.
- STOP at the end of every phase and wait for my approval.
- No stubs presented as done. If something isn't finished, list it under "Not done".
- Each module has tests. Keep modules small with clear interfaces.
- No secrets in code. Use .env and .env.example.
- Tell me the exact commands to run and what output to expect.
- Never weaken, skip or delete an existing test to make something pass.
- Run `python -m pytest -q` from backend/ after every change and show me the output.