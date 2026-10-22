# SatQuery AI — Testing Strategy

## 1. Overview

Testing is organised into four layers, plus a dedicated ML evaluation plan and a query-understanding test set. The principle is: **fast tests run constantly; slow tests run before merge; ML evaluation runs on schedule.**

```
┌───────────────────────────────────────────┐
│          Layer 4: E2E / Smoke             │  ← Playwright + real API (nightly)
├───────────────────────────────────────────┤
│          Layer 3: Integration             │  ← DB + Sentinel-2 mock (per PR)
├───────────────────────────────────────────┤
│          Layer 2: API Contract            │  ← FastAPI TestClient (per PR)
├───────────────────────────────────────────┤
│          Layer 1: Unit                    │  ← Pure functions, no I/O (per save)
└───────────────────────────────────────────┘
```

---

## 2. Layer Details

### 2.1 Unit Tests

**Scope:** Pure logic with no database, network, or file-system calls.

| Module | What's tested | Example |
|---|---|---|
| `operations/ndvi.py` | NDVI formula on synthetic arrays | `assert ndvi(nir=0.5, red=0.1) ≈ 0.667` |
| `operations/change_detection.py` | Diff computation, threshold filtering | Diff of two NDVI arrays → expected change map |
| `query_parser/schema.py` | Pydantic validation, ask-back logic | Missing `aoi` → `ValidationError` with correct field |
| `sentinel2/search.py` | ODATA query construction | Date range + bbox → correct query string |
| `tiles/slicer.py` | Tile grid generation | 1024×1024 image → 16 tiles of 256×256 |
| `ml/predict.py` | Pre/post-processing (not inference) | Normalisation, patch extraction, class mapping |

**Framework:** `pytest` with `pytest-cov` (target: 85% line coverage for business logic)

**Run:** On every file save via IDE watcher; CI on every push.

---

### 2.2 API Contract Tests

**Scope:** HTTP-level tests using FastAPI's `TestClient` (no real server process). Database is an in-memory SQLite or test PostgreSQL.

| Endpoint | Test Cases |
|---|---|
| `POST /api/v1/query` | Valid query → 202; missing AOI → 422 ask-back; gibberish → 400 |
| `GET /api/v1/analyses/{id}` | Existing → 200 with correct fields; non-existent → 404 |
| `GET /api/v1/jobs/{id}` | Completed job has `result_summary` and `result_raster_url` |
| `POST /api/v1/aois` | Valid polygon → 201; self-intersecting → 400 |
| `GET /api/v1/tiles/{job_id}/{z}/{x}/{y}.png` | Valid tile → 200 image/png; out-of-bounds → 204 |
| Auth | Missing API key → 401; invalid key → 403 |

**Framework:** `pytest` + `httpx.AsyncClient` (FastAPI-native)

---

### 2.3 Integration Tests

**Scope:** Multi-component flows with real database (test PostgreSQL) and mocked external services.

| Flow | Components Involved | External Mocks |
|---|---|---|
| Query → Job → Result | Parser, Orchestrator, NDVI op, DB | LLM API (recorded responses), Sentinel-2 API (canned scenes) |
| AOI geocoding | API, Geocoder | Nominatim (recorded) |
| Scene search + download | Sentinel-2 Client, Cache | Copernicus ODATA (recorded responses + fixture GeoTIFFs) |
| Change detection pipeline | Orchestrator, CD op, DB | Scene fixtures |
| ML classification pipeline | Orchestrator, Classify op, DB | Model inference on fixture tiles |

**Mock strategy:**
- HTTP mocks via `respx` (for `httpx` client) or `responses` (for `requests`)
- Fixture GeoTIFFs: 3 small (256×256, 4-band) synthetic scenes stored in `tests/fixtures/`
- LLM mock: recorded JSON responses for 20 reference queries

---

### 2.4 End-to-End / Smoke Tests

**Scope:** Full stack running (Docker Compose), real browser interaction.

| Test | Checks |
|---|---|
| Homepage loads | Map renders, query input visible |
| Simple NDVI query | Type query → job created → progress shown → result layer on map |
| Ask-back flow | Incomplete query → clarification displayed → answer → result |
| History sidebar | Previous analysis appears in list, click re-loads result |

**Framework:** Playwright (Python) against the Docker Compose stack.

**Run:** Nightly CI job; before release tags.

---

## 3. Query-Understanding Test Set

A curated set of natural-language inputs with expected `StructuredQuery` outputs, used to evaluate the LLM parser.

### 3.1 Dataset Structure

```
tests/query_eval/
├── dataset.json          # Array of test cases
├── evaluate.py           # Scoring script
└── results/              # Evaluation run outputs
```

### 3.2 Test Case Format

```json
{
  "id": "q-001",
  "input_text": "Show NDVI for Delhi NCR in March 2024",
  "lang": "en",
  "expected": {
    "operations": ["ndvi"],
    "aoi.place_name": "Delhi NCR",
    "date_range.start": "2024-03-01",
    "date_range.end": "2024-03-31"
  },
  "tags": ["simple", "ndvi", "english", "place_name"]
}
```

### 3.3 Test Categories

| Category | Count (target) | Examples |
|---|---|---|
| Simple NDVI | 15 | "NDVI for [place] in [month] [year]" |
| Change detection | 15 | "Compare vegetation before and after monsoon" |
| Hindi queries | 15 | "दिल्ली में हरियाली कैसी है?" |
| Ambiguous (needs ask-back) | 10 | "What's the greenery like?" (no location, no date) |
| Out-of-scope (should reject) | 10 | "What's the weather?", "Send me an email" |
| Complex / multi-operation | 10 | "NDVI + classification for Varanasi, last 6 months" |
| Edge cases | 10 | Future dates, huge AOIs, misspellings |
| **Total** | **85** | |

### 3.4 Scoring Metrics

| Metric | Definition | Target |
|---|---|---|
| **Operation accuracy** | Correct operations set | ≥ 90% |
| **Field extraction F1** | Per-field precision/recall across all test cases | ≥ 0.85 |
| **Ask-back precision** | When it asks back, it should need to | ≥ 0.90 |
| **Ask-back recall** | When info is missing, it should ask back | ≥ 0.85 |
| **Rejection accuracy** | Out-of-scope correctly rejected | ≥ 0.90 |
| **Hindi parity** | Hindi accuracy within 5% of English | Delta ≤ 5% |

### 3.5 Evaluation Cadence

- Run after any change to the system prompt or schema
- Run after LLM model version upgrades
- Track scores over time in `tests/query_eval/results/`

---

## 4. ML Model Evaluation

(Detailed in [ML_STRATEGY.md](file:///c:/Users/Dell/Downloads/satquery_ai/docs/ML_STRATEGY.md) §5; summary here)

| Metric | EuroSAT Test Target | Indian Val Target |
|---|---|---|
| 10-class accuracy | ≥ 92% | ≥ 75% |
| 5-class accuracy | ≥ 95% | ≥ 82% |
| Per-class F1 | ≥ 0.85 | ≥ 0.65 |
| Confidence calibration (ECE) | ≤ 0.05 | ≤ 0.10 |

**Evaluation artifacts:**
- Confusion matrices (10-class and 5-class)
- Per-class precision/recall/F1 table
- Reliability diagram (calibration)
- Accuracy-vs-confidence-threshold curve

---

## 5. Pipeline Timing Benchmarks

Performance benchmarks run as part of integration tests to catch regressions.

| Pipeline Stage | Metric | Target (MVP) | How Measured |
|---|---|---|---|
| Query parsing (LLM) | Latency p95 | < 3s | Timer around LLM API call |
| Sentinel-2 catalogue search | Latency p95 | < 5s | Timer around ODATA call |
| Scene download (cache miss) | Throughput | > 10 MB/s | Bytes / time |
| Scene download (cache hit) | Latency p95 | < 200ms | File-read time |
| NDVI computation (100 km²) | Wall-clock | < 30s | Timer around operation |
| Change detection (100 km²) | Wall-clock | < 60s | Timer around operation |
| ML classification (10 km²) | Wall-clock (CPU) | < 30s | Timer around operation |
| Tile rendering | Latency p95 | < 100ms per tile | Timer around tile server |
| Full pipeline (query → result) | Wall-clock | < 2 min (10 km² NDVI) | End-to-end timer |

**Regression rule:** If any benchmark degrades > 20% vs. baseline, the CI run fails with a warning (not a block, but visible).

---

## 6. Test Infrastructure

### 6.1 CI Pipeline (GitHub Actions)

```yaml
# Simplified flow
on: [push, pull_request]

jobs:
  unit:
    runs-on: ubuntu-latest
    steps: [checkout, install, pytest tests/unit --cov]

  api-contract:
    runs-on: ubuntu-latest
    services: [postgres]
    steps: [checkout, install, pytest tests/api]

  integration:
    runs-on: ubuntu-latest
    services: [postgres]
    steps: [checkout, install, pytest tests/integration]

  e2e:  # nightly only
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    steps: [checkout, docker-compose up, playwright, docker-compose down]

  query-eval:
    runs-on: ubuntu-latest
    steps: [checkout, install, python tests/query_eval/evaluate.py]
```

### 6.2 Test Data Management

| Data | Location | Size | Git-tracked? |
|---|---|---|---|
| Synthetic GeoTIFFs (256×256, 4-band) | `tests/fixtures/scenes/` | ~5 MB total | Yes |
| Query eval dataset | `tests/query_eval/dataset.json` | ~50 KB | Yes |
| ML eval patches (EuroSAT subset) | `tests/fixtures/ml/` | ~100 MB | Git LFS |
| Indian validation patches | `tests/fixtures/ml_india/` | ~50 MB | Git LFS |
| Recorded HTTP responses | `tests/fixtures/cassettes/` | ~2 MB | Yes |
