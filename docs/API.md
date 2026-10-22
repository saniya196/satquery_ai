# SatQuery AI REST API

The API is served by FastAPI. Interactive OpenAPI documentation is available at `/docs` while the service is running. JSON request and response bodies use WGS84 GeoJSON for AOIs. No authentication is implemented in this MVP.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness response. |
| `POST` | `/aoi/validate` | Validate an AOI GeoJSON geometry. |
| `POST` | `/query/parse` | Parse a question and return structured query plus clarification, if needed. |
| `POST` | `/analysis/run` | Validate and enqueue a single-AOI analysis. |
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

`GET /analysis/{job_id}/layers` returns Leaflet bounds in `[[south, west], [north, east]]` order and a `layers` mapping of available layer names to value ranges and legend colors. The corresponding `/layer/{name}.png` path serves a PNG. Layer arrays are held in process memory for up to 20 completed raster jobs; they are not restored from history after a service restart.

CSV and GeoJSON exports are generated only from the stored completed result. They return 404 for an unknown job or a record without a completed result. CSV includes scalar facts/confidence/evidence metrics and one row per available time-series value/rolling mean/anomaly. GeoJSON is a Feature whose geometry is the saved AOI and whose properties are the result facts.

## Errors and limits

- AOI validation, parser clarification in compare mode, and analysis-domain errors return HTTP 422.
- Unknown job/history IDs return 404.
- A job can fail when imagery is absent, cloud/valid-pixel thresholds are not met, scenes cannot share a grid, or a model is unavailable.
- The job-status dictionary and rendered layer store are process-local. SQLite history persists completed/failed records but is not a distributed job queue.
