# SatQuery AI REST API

The API is served by FastAPI. Interactive OpenAPI documentation is available at `/docs` while the service is running. JSON request and response bodies use WGS84 GeoJSON for AOIs. No authentication is implemented in this MVP.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness response. |
| `GET` | `/evaluation/land-cover` | Return the checked-in EuroSAT model evaluation report and scope caveats; does not rerun evaluation. |
| `POST` | `/aoi/validate` | Validate an AOI GeoJSON geometry. |
| `POST` | `/query/parse` | Parse a question and return structured query plus clarification, if needed. |
| `POST` | `/analysis/run` | Validate and enqueue a single-AOI analysis. |
| `POST` | `/analysis/investigate` | Run a bounded, evidence-grounded investigation and return its plan, execution history, findings, validation, and explanation. |
| `GET` | `/jobs/{job_id}` | Read in-memory job state and completed result. |
| `GET` | `/history` | List finished records newest first, summary fields only. |
| `GET` | `/history/{job_id}` | Retrieve full stored query, structured query, AOI, status, and result. |
| `DELETE` | `/history/{job_id}` | Delete one stored history record. |
| `POST` | `/analysis/compare` | Run one operation for two AOIs and return both results plus numeric differences. |
| `GET` | `/analysis/{job_id}/layers` | Get WGS84 bounds and available raster legends. |
| `GET` | `/analysis/{job_id}/layer/{name}.png` | Get an RGBA PNG layer (`index`, `diff`, `classes`, `hotspots`, `landcover`). |
| `GET` | `/analysis/{job_id}/export.csv` | Export stored result facts and per-date series rows, when present. |
| `GET` | `/analysis/{job_id}/export.geojson` | Export the stored AOI Polygon with result facts as Feature properties. |
| `POST` | `/grounding/check` | Check an answer against a supplied facts object. |

## Validate AOI

`POST /aoi/validate`

```json
{
  "aoi": {
    "type": "Polygon",
    "coordinates": [[[78.0, 17.0], [78.01, 17.0], [78.01, 17.01], [78.0, 17.01], [78.0, 17.0]]]
  }
}
```

A valid polygon returns `valid`, its bounds, and geometry type. Invalid geometry returns HTTP 422 with a code and message.

## Parse a question

`POST /query/parse`

```json
{"query":"Did vegetation decrease between June and September?","reference_date":"2026-10-18"}
```

The response contains `structured_query` and `clarification`. The parser does not invent missing periods.

## Land-cover evaluation report

`GET /evaluation/land-cover` serves the metrics recorded in `models/metrics.json`. The report includes the available EuroSAT held-out test metrics, test sample count, source files, and applicability limitations. It is a report of the existing checkpoint artifact, not a reproducible evaluation run: this endpoint does not load the dataset or rerun inference, and accuracy on Indian Sentinel-2 L2A scenes remains unmeasured. If the artifact is missing or invalid, the endpoint returns HTTP 503 rather than a success-shaped placeholder.

## Run an analysis

`POST /analysis/run`

```json
{
  "query": "Did vegetation health decrease between June and September?",
  "aoi": {
    "type": "Polygon",
    "coordinates": [[[78.0, 17.0], [78.01, 17.0], [78.01, 17.01], [78.0, 17.01], [78.0, 17.0]]]
  },
  "reference_date": "2026-10-18",
  "max_cloud": 40
}
```

A missing/unsupported query returns `{"status":"needs_clarification","message":"..."}`. An actionable query returns `{"status":"queued","job_id":"..."}`. The API uses FastAPI BackgroundTasks; poll `GET /jobs/{job_id}` until `completed` or `failed`. A completed job includes `result`; a failed job includes `error.code` and `error.message`.

## Run an investigation

`POST /analysis/investigate` runs the existing deterministic analysis tools synchronously and returns an execution history. It does not create a background job or report live progress. The request accepts the same natural-language question and AOI context as `/analysis/run`; optional date overrides can supply missing periods without changing the question text.

```json
{
  "query": "Investigate vegetation changes and identify significant decrease hotspots between June and September",
  "aoi": {
    "type": "Polygon",
    "coordinates": [[[78.0, 17.0], [78.01, 17.0], [78.01, 17.01], [78.0, 17.01], [78.0, 17.0]]]
  },
  "reference_date": "2026-10-07"
}
```

The response contains `question_understood`, `plan`, `trace`, `tools_executed`, `actual_findings`, `supporting_evidence`, `data_quality_and_uncertainty`, `unsupported_conclusions`, `suggested_next_investigations`, and a grounded `explanation`. A response with `status: "needs_input"` does not execute a tool. `completed`, `partial`, and `failed` statuses reflect actual tool outcomes. Raster arrays are intentionally excluded from the JSON investigation envelope; map rasters remain available only through the normal persisted analysis workflow.

## History

`GET /history` returns `{"items":[...]}` newest first. Each item contains `id`, `created`, `query`, `status`, and `operation`; it does not include the result payload. `GET /history/{job_id}` returns the full record:

```json
{
  "id": "job-id",
  "created": "2026-10-18T12:00:00+00:00",
  "query": "Show NDVI for June",
  "structured_query": {},
  "aoi": {"type":"Polygon","coordinates":[]},
  "status": "completed",
  "result": {"evidence": {}, "confidence": {}, "facts": {}, "answer": {}}
}
```

Unknown records return 404. `DELETE /history/{job_id}` returns 204 when deleted and 404 when not found. The SQLite file is selected with `SATQUERY_DB`; the default native path is `backend/.data/satquery.db` when run from the backend directory.

## Compare two AOIs

`POST /analysis/compare` accepts `query`, `aoi_a`, `aoi_b`, optional `reference_date`, and `max_cloud`. The same parsed operation runs through the analysis services for both geometries. The response contains `structured_query`, `aoi_a.result`, `aoi_b.result`, and `differences` (`B - A` for shared numeric metrics). Missing query information or invalid AOIs return HTTP 422. Comparison results are returned directly and are not added to history.

## Map layers and exports

`GET /analysis/{job_id}/layers` returns Leaflet bounds in `[[south, west], [north, east]]` order and a `layers` mapping of available layer names to value ranges and legend colors. The corresponding `/layer/{name}.png` path serves a PNG.

**Persistence and restart recovery:** History records (including stored analysis metrics/results where present) and job metadata are persisted in SQLite when available. Raster arrays and georeferencing metadata are persisted as filesystem artifacts when artifact saving succeeds. The in-memory layer cache is process-local and limited to the current backend process (up to 20 recent jobs). After a backend restart, raster layers can be restored from filesystem artifacts when the required completed job or history information and valid artifacts are available (including required georeferencing metadata such as `transform` and `crs`). History-only completed records can also recover raster layers when their original artifacts exist.

**Limitations:** If artifacts are missing, invalid, or lack required georeferencing metadata, historical metrics may remain available via `/history/{job_id}` while raster layers are unavailable. Failed and non-completed jobs cannot serve completed analysis layers. Not every historical record can restore its map, and missing raster artifacts cannot be reconstructed.

CSV and GeoJSON exports are generated only from the stored completed result. They return 404 for an unknown job or a record without a completed result. CSV includes scalar facts/confidence/evidence metrics and one row per available time-series value/rolling mean/anomaly. GeoJSON is a Feature whose geometry is the saved AOI and whose properties are the result facts.

## Errors and limits

- AOI validation, parser clarification in compare mode, and analysis-domain errors return HTTP 422.
- Unknown job/history IDs return 404.
- A job can fail when imagery is absent, cloud/valid-pixel thresholds are not met, scenes cannot share a grid, or a model is unavailable.
- The in-memory job-status dictionary and layer cache are process-local. SQLite persists history records and, when available, job metadata; filesystem artifacts may persist raster data for completed analyses, but this is not a distributed job queue and restart recovery depends on valid persisted metadata/artifacts.
