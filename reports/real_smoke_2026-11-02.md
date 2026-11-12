# SatQuery AI — Real Sentinel-2 Smoke Test Report

Date: 2026-11-02
Diagnostic only: False
Max cloud: 30.0, Days back: 90

## Stage timings

- delhi:stac_search:6.33s
- delhi:analysis:8.34s
- mumbai:stac_search:5.52s
- mumbai:analysis:188.27s
- bengaluru:stac_search:8.97s

## Results

### delhi
- Scene: S2C_43RGM_20260821_0_L2A
- Date: 2026-08-21T05:41:00.352000+00:00
- Cloud: 21.205589
- Valid pixel fraction: 1.0
- CRS: EPSG:32643
- Duration: 14.68s
- NDVI stats: {"n_total": 4337636, "n_valid": 4337636, "valid_fraction": 1.0, "mean": 0.41324675477764633, "median": 0.42878147434140945, "min": -0.4677031278919119, "max": 0.9993726474278545, "std": 0.2694784402268857, "coverage_fraction": 0.6038641785525573}

### mumbai
- Scene: S2B_42QZG_20260908_0_L2A
- Date: 2026-09-08T05:53:39.160000+00:00
- Cloud: 27.592099
- Valid pixel fraction: 0.9999954946411975
- CRS: EPSG:32643
- Duration: 193.79s
- NDVI stats: {"n_total": 4661116, "n_valid": 4661095, "valid_fraction": 0.9999954946411975, "mean": 0.3019913905524775, "median": 0.31081081081081086, "min": -0.9942528735632182, "max": 0.9992239037640668, "std": 0.4164647016527293, "coverage_fraction": 0.5082164169578178}

## Errors / Limitations

- bengaluru:unknown:RasterioIOError:Read failed. See previous exception for details.
