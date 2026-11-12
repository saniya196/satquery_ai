# SatQuery AI — Scientific Evaluation Report Format

Use this template for reproducible evaluation runs. Fill in every section; mark unknowns as "unknown" rather than guessing.

## Run metadata
- Report ID (e.g., EVAL-YYYY-MM-DD-001)
- Date/time of run (UTC)
- Commit hash / branch
- Tester
- Environment (OS, Python, deps)
- Test type: `synthetic` | `real_sentinel2` | `mixed`

## Dataset / source
- Data source: Sentinel-2 L2A via STAC (provider name + endpoint)
- Collection/item IDs
- Tile (MGRS)
- Orbit / granule if known
- Cloud cover (per scene)
- CRS of source scenes
- Access method (search parameters)

## AOI
- AOI description / location
- Geometry (GeoJSON)
- Area (km²)
- CRS used for analysis
- Valid-pixel rationale

## Dates / time window
- Date A / range A
- Date B / range B
- Seasonality notes
- Temporal gap (days)

## Processing settings
- Index(es)
- Change thresholds (if change detection)
- Max cloud
- min_valid_fraction
- savi_l
- Bands used
- Resampling (bilinear/nearest) and alignment details
- SCL classes excluded
- Reflectance scale/offset applied

## Expected results
- Expected index values / statistics (with rationale / hand calculation)
- Expected change classes / hotspots (with rationale)
- Expected trends (if applicable) - state caveats
- Ground truth source (if any). If none, state "no ground truth".

## Actual results
- Computed values (index stats, change metrics, hotspots)
- Evidence object summary (scenes, bands, formula, preprocessing, valid-pixel %, thresholds)
- Confidence score + components
- Warnings / errors

## Verification
- Manual checks performed
- Discrepancies
- Agreement assessment (qualitative)
- Pass/fail with justification

## Known limitations
- Spatial autocorrelation / p-value caveats
- Model applicability (EuroSAT L1C vs L2A)
- Cloud/shadow residuals
- Alignment limitations
- Any unsupported claims
