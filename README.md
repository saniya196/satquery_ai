# SatQuery AI

SatQuery AI is a map-first satellite intelligence workspace. Users draw an area of interest, ask a question in natural language, and receive an evidence-backed analysis of Sentinel-2 imagery.

## Problem

Satellite imagery is abundant, but answering an area-specific question still requires remote-sensing expertise, careful preprocessing, and reproducible calculations. Cloud cover, missing scenes, projection details, and model uncertainty can easily be hidden behind a polished map or an ungrounded narrative.

## Motivation

Make common landscape questions accessible without turning the language model into a calculator. The user supplies the question and AOI; the platform locates suitable data, applies explicit remote-sensing methods, and returns computed values with their supporting evidence and limitations.

## Solution

The frontend combines a Leaflet map, AOI drawing/upload tools, query entry, job progress, history, exports, and result views. FastAPI parses questions into a structured operation, obtains Sentinel-2 L2A scenes through a provider abstraction, executes deterministic analysis, and returns evidence plus a grounded answer. Completed jobs and results are recorded in SQLite; scene reads are cached on disk.

Supported analysis operations are index statistics, before/after change detection, time-series trend analysis, and land-cover classification. Unsupported or incomplete questions are rejected or clarified rather than guessed.

## Key innovation

The language model is kept outside the numerical path. It may interpret a question and phrase an explanation, but all dates, metrics, confidence values, change classes, and predictions shown by the application come from deterministic code and structured results. Generated explanations are checked against those results, with deterministic templates as fallback.

## Architecture

The implemented components and request/data flow are described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The REST routes are listed in [docs/API.md](docs/API.md).

## Data flow

1. The user draws or uploads a GeoJSON Polygon and asks a question.
2. The parser produces a structured operation, dates, and index, or returns a clarification.
3. The provider searches Element84 Earth Search for Sentinel-2 L2A scenes and reads COG windows covering the AOI.
4. Preprocessing scales reflectance from asset metadata, aligns bands, and applies SCL/AOI validity masks.
5. The operation computes indices, change classes, time-series statistics, or land-cover classes.
6. Evidence, confidence, and grounded answer are returned; completed results are stored in SQLite.
7. The frontend polls job status, displays result layers and metrics, and offers history and exports.

## AI/ML components

- **Question interpretation:** the rule-based English/Hindi parser works without a key, including month names, explicit years/ranges, and relative trend periods. An optional Gemini client can emit the same structured query shape.
- **Answer phrasing:** the LLM receives structured facts only. Numeric/date claims are validated against the result; a deterministic template is used when needed.
- **Land cover:** NumPy inference for a ResNet18 model trained on EuroSAT, using five Sentinel-2 bands and 64×64-pixel tiles. Weights are loaded from `models/`; training is not part of the API container.

## Remote-sensing methods

- NDVI: `(B08 - B04) / (B08 + B04)`.
- NDWI (McFeeters): `(B03 - B08) / (B03 + B08)`.
- MNDWI: `(B03 - B11) / (B03 + B11)`.
- NDBI: `(B11 - B08) / (B11 + B08)`.
- SAVI: `((B08 - B04) / (B08 + B04 + L)) * (1 + L)`, with `L = 0.5`.
- B11 is aligned to the 10 m grid; continuous bands use bilinear resampling and SCL uses categorical resampling.
- SCL invalid classes include no-data, saturated/defective, cloud shadow, medium/high cloud, cirrus, and snow/ice. Divide-by-zero and invalid pixels remain nodata; analyses below the configured valid-pixel minimum are refused.
- Trend calculations use AOI medians by date, Mann-Kendall and Sen's slope. Fewer than eight valid dates do not support a trend claim. Seasonality and autocorrelation caveats are retained in the result.

## Deterministic computation principle

The language model does not compute metrics or invent metadata. Indices, class areas, trend statistics, confidence scores, and change thresholds are calculated by backend code. Every analysis result includes evidence describing source scenes, dates, bands, formula, preprocessing, valid-pixel fraction, thresholds, and operation metrics. Missing or inadequate data causes a clear failure or clarification rather than a synthetic answer.

## Screenshots

- **Workspace:** `[Screenshot placeholder: replace with a real capture saved in docs/images/workspace.png.]`
- **Completed analysis:** `[Screenshot placeholder: replace with a real capture saved in docs/images/analysis-result.png.]`
- **Area comparison:** `[Screenshot placeholder: replace with a real capture saved in docs/images/area-comparison.png.]`

No screenshots are included yet; these placeholders are not product imagery.

## Example queries

- `Did vegetation health decrease between June and September?`
- `Show NDVI for June`
- `Show land cover for June`
- `Show the vegetation trend over the last year`
- `Show NDWI for 2025`
- `Show NDVI trend from 2022 to 2025`
- `जून 2026 में NDVI दिखाएं`
- `पिछले साल का NDVI रुझान दिखाएं`

Dates and supported operation details are required. The parser asks for missing periods instead of assuming them.

## Evaluation/results

No `docs/EVALUATION.md` is present in this repository, so end-to-end parser accuracy, query latency, successful-query rate, and sensitivity results are not reported here.

The checked-in `models/metrics.json` reports EuroSAT test-set results for the current land-cover model: 10-class accuracy `0.9874`, 10-class macro-F1 `0.9871`, 4-product-class accuracy `0.9928`, 4-product-class macro-F1 `0.9927`, and expected calibration error `0.0032`. These are dataset test metrics, not accuracy estimates for Indian L2A scenes. See [models/MODEL_CARD.md](models/MODEL_CARD.md) for the full model card and limits.

## Installation

### Native development (Windows CMD)

Backend, from the repository root:

```cmd
cd /d C:\path\to\satquery_ai\backend
py -3.13 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8001
```

In another CMD window, frontend:

```cmd
cd /d C:\path\to\satquery_ai\frontend
npm ci
set VITE_API_URL=http://localhost:8001
npm run dev -- --host localhost
```

Open `http://localhost:5173`. The optional Gemini key can be set in the backend CMD session as `set GEMINI_API_KEY=...`; the rule-based parser runs without it. Never commit real keys. The backend listens on `http://127.0.0.1:8001`.

### Docker Compose (Windows CMD)

From the repository root:

```cmd
copy .env.example .env
notepad .env
docker compose up --build
```

Set any real provider key directly in the local `.env` file. Open the UI at `http://localhost:8080` and API docs at `http://localhost:8001/docs`. SQLite data and scene cache persist in named Docker volumes; `models/` is mounted read-only. Stop the services with `docker compose down`.

## API documentation

The running OpenAPI interface is at `http://localhost:8001/docs`. Implemented route summary:

- `GET /health`
- `POST /aoi/validate`
- `POST /query/parse`
- `POST /analysis/run`, `GET /jobs/{job_id}`
- `GET /history`, `GET /history/{job_id}`, `DELETE /history/{job_id}`
- `POST /analysis/compare`
- `GET /analysis/{job_id}/layers`, `GET /analysis/{job_id}/layer/{name}.png`
- `GET /analysis/{job_id}/export.csv`, `GET /analysis/{job_id}/export.geojson`
- `POST /grounding/check`

See [docs/API.md](docs/API.md) for request and response details.

## Limitations

- The land-cover model was trained on Sentinel-2 **L1C** top-of-atmosphere EuroSAT imagery, while the application supplies **L2A** surface-reflectance data; this domain shift can affect predictions.
- Training data is European. Accuracy on Indian landscapes is **unmeasured** until validated on locally labelled imagery.
- EuroSAT has **no bare-soil class**, so the model cannot report bare soil.
- 64×64-pixel tiles receive one class; mixed pixels and boundaries can be represented coarsely.
- Model confidence is a softmax score, not scientific certainty. Calibration metrics describe EuroSAT only.
- Live data access depends on the STAC provider and network availability. Coverage, clouds, valid-pixel limits, and scene-grid mismatches can prevent an analysis.
- The current jobs registry is in-memory; SQLite stores finished history, but does not provide a durable distributed job queue.

## Future work

- Validate land-cover performance on labelled local L2A imagery and add an explicit bare-soil methodology only if supported by data.
- Improve AOI-aware multi-scene compositing and support more robust treatment of seasonal time series.
- Add operational monitoring, authentication, access controls, and a durable job queue when deployment needs justify them.
- Expand evaluation with a versioned, reproducible query test set and synthetic pipeline/sensitivity reports.
