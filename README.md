\# SatQuery AI (SIH26167)



Interactive Vision-Language Assistant for Multimodal Remote Sensing Image Analysis — Review 1 (\~30% implementation).



\## What it does



Upload a 13-band Sentinel-2 (.tif) satellite image, ask a natural-language question, and get an answer grounded in real computed values — land-cover classification, NDVI/NDWI spectral indices, a highlighted evidence region, and a confidence score.



\## Features implemented (Review 1)



1\. Grounded natural-language querying

2\. Land-cover classification (ResNet18, fine-tuned on EuroSAT, 92-93% validation accuracy)

3\. Spectral index computation (NDVI, NDWI)

4\. Evidence region highlighting (visual overlay on the actual image)

5\. Confidence scoring

6\. Query history (SQLite)



\## Run locally



\*\*Backend:\*\*

cd backend

venv\\Scripts\\activate

uvicorn main:app --reload --port 8000





\*\*Frontend:\*\*



cd frontend

npm run dev



Open http://localhost:5173



\## Tech stack



React (Vite), FastAPI, PyTorch/torchvision, rasterio, SQLite



\## Dataset



EuroSAT (Helber et al., 2019) — 27,000 labeled Sentinel-2 patches, 10 land-cover classes, 13 spectral bands.



\## Roadmap (Review 2 onward)



SAR imagery support, multitemporal change detection, RAG-based domain knowledge, geospatial reasoning, fine-tuned vision-language model.

