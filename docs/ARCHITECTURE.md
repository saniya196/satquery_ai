# SatQuery AI Architecture

## Scope

This document describes the implemented MVP. The browser application is React, Vite, TypeScript, and Leaflet. The API and analysis pipeline are FastAPI and Python. Sentinel-2 L2A assets are discovered through Element84 Earth Search and read from COGs over the AOI. Completed job records are stored in SQLite; downloaded scene arrays are cached on disk.

## Component diagram

```mermaid
graph LR
    subgraph Browser["Browser: React + TypeScript"]
        Map[Leaflet map and AOI tools]
        Query[Query and job controls]
        History[History and comparison]
        Results[Metrics, charts, evidence]
    end

    subgraph API["FastAPI application"]
        Routes[REST routes]
        Parser[Rule parser / optional Gemini parser]
        Dispatcher[Operation dispatcher]
        Grounding[Grounded response validator]
        LayerStore[In-memory raster layer store]
    end

    subgraph Engine["Deterministic analysis modules"]
        Provider[SatelliteProvider]
        Mask[Reflectance scaling and SCL/AOI masks]
        Indices[Spectral indices and statistics]
        Change[Change detection]
        Trend[Mann-Kendall and Sen slope]
        LandCover[NumPy ResNet18 classifier]
        Evidence[Evidence and confidence]
    end

    subgraph Persistence["Local persistence"]
        STAC[Element84 Earth Search STAC]
        COG[Sentinel-2 L2A COG assets]
        Cache[Disk scene cache]
        SQLite[(SQLite history)]
        Models[Read-only models directory]
    end

    Map --> Routes
    Query --> Routes
    History --> Routes
    Routes --> Parser
    Parser --> Dispatcher
    Dispatcher --> Provider
    Provider --> STAC
    Provider --> COG
    Provider <--> Cache
    Provider --> Mask
    Mask --> Indices
    Mask --> Change
    Mask --> Trend
    Mask --> LandCover
    Models --> LandCover
    Indices --> Evidence
    Change --> Evidence
    Trend --> Evidence
    LandCover --> Evidence
    Evidence --> Grounding
    Grounding --> Routes
    Dispatcher --> LayerStore
    Routes --> SQLite
    Routes --> Results
    LayerStore --> Map
    Results --> Map
```

## Data-flow diagram

```mermaid
sequenceDiagram
    actor User
    participant UI as React/Leaflet UI
    participant API as FastAPI
    participant Parser as Query parser
    participant Provider as SatelliteProvider
    participant STAC as Earth Search STAC
    participant Cache as Disk scene cache
    participant Engine as Analysis service
    participant Evidence as Evidence/grounding
    participant DB as SQLite history

    User->>UI: Draw/upload AOI and submit query
    UI->>API: POST /analysis/run {query, aoi, reference_date}
    API->>Parser: Parse to StructuredQuery
    alt Required details missing or query unsupported
        Parser-->>API: Clarification message
        API-->>UI: needs_clarification
    else Query is actionable
        API-->>UI: queued job_id
        API->>Engine: Run selected operation
        Engine->>Provider: Find required scenes for AOI/date range
        Provider->>STAC: Search Sentinel-2 L2A metadata
        STAC-->>Provider: Scene/item metadata
        Provider->>Cache: Read cached AOI/band arrays when available
        alt Cache miss
            Provider->>Provider: Windowed COG reads and reflectance scaling
            Provider->>Cache: Persist scene arrays and grid metadata
        end
        Provider-->>Engine: Scaled and aligned bands, SCL, AOI mask
        Engine->>Engine: Deterministic index/change/trend/classification
        Engine->>Evidence: Metrics, evidence, confidence
        Evidence->>Evidence: Validate every generated numeric/date claim
        Evidence-->>API: Structured result and answer
        API->>DB: Store finished job, query, AOI, and result
        API-->>UI: Completed job result
        UI->>API: GET /analysis/{id}/layers and layer PNGs
        API-->>UI: Bounds, legends, RGBA PNGs
        UI-->>User: Summary, maps, metrics, evidence, exports
    end
```

## Runtime boundaries

- The LLM is an optional query interpreter and explanation writer. Analysis services compute metrics and confidence; LLM output is not a source of measurements.
- `SatelliteProvider` hides STAC search and COG access from analysis services. The current provider is Element84 Earth Search.
- Raster reads are limited to the AOI bounding window. Product scale/offset metadata is used before index calculation; SCL and AOI masks control valid pixels.
- `backend/.cache/satquery` is the native scene cache path. In Compose it is mounted to the `satellite-cache` volume.
- Completed history records use SQLite at `SATQUERY_DB`; Compose mounts the `satquery-db` volume at `/app/.data`.
- Rendered arrays are retained in process memory for up to 20 jobs. They are not part of the SQLite record and disappear when the API process restarts.
- Land-cover weights and metadata are loaded from `SATQUERY_MODEL_DIR`; Compose mounts the repository `models/` directory read-only.

## Deployment topology

```mermaid
graph LR
    Browser[Browser] -->|HTTP :8080| Nginx[Frontend Nginx static server]
    Browser -->|HTTP API :8001| API[FastAPI / Uvicorn]
    API --> DB[(SQLite named volume)]
    API --> Cache[(Scene cache named volume)]
    API --> Models["./models mounted read-only"]
    API --> STAC[Earth Search and Sentinel-2 COGs]
```

The browser calls the API directly; `VITE_API_URL` is compiled into the frontend bundle. `SATQUERY_CORS_ORIGINS` must include the browser origin. Docker Compose defaults to `http://localhost:8080` for the frontend and `http://localhost:8001` for the API.
