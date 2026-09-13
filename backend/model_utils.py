import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "ml", "src"))

import torch
import torch.nn as nn
import torchvision
import numpy as np
from PIL import Image
from rasterio.io import MemoryFile

from preprocessing import compute_ndvi, compute_ndwi, get_rgb_preview, summarize_index

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "eurosat_classifier.pt")

_checkpoint = torch.load(MODEL_PATH, map_location="cpu")
CLASS_NAMES = _checkpoint["class_names"]

_model = torchvision.models.resnet18(weights=None)
_model.fc = nn.Linear(_model.fc.in_features, len(CLASS_NAMES))
_model.load_state_dict(_checkpoint["model_state"])
_model.eval()

MEAN = np.array([0.485, 0.456, 0.406])
STD = np.array([0.229, 0.224, 0.225])


def load_bands_from_bytes(file_bytes: bytes) -> np.ndarray:
    with MemoryFile(file_bytes) as memfile:
        with memfile.open() as src:
            return src.read().astype(np.float32)


def classify_rgb_preview(rgb: np.ndarray) -> dict:
    """rgb: HxWx3 float array in [0,1]. Resizes, normalizes, runs classifier."""
    img = Image.fromarray((rgb * 255).astype(np.uint8)).resize((64, 64))
    arr = np.array(img).astype(np.float32) / 255.0
    arr = (arr - MEAN) / STD
    tensor = torch.tensor(arr.transpose(2, 0, 1), dtype=torch.float32).unsqueeze(0)

    with torch.no_grad():
        logits = _model(tensor)
        probs = torch.softmax(logits, dim=1)[0]
        pred_idx = int(torch.argmax(probs))
        confidence = float(probs[pred_idx])

    return {"class": CLASS_NAMES[pred_idx], "confidence": round(confidence, 4)}


def analyze_tif(file_bytes: bytes) -> dict:
    bands = load_bands_from_bytes(file_bytes)
    ndvi = compute_ndvi(bands)
    ndwi = compute_ndwi(bands)
    rgb = get_rgb_preview(bands)

    classification = classify_rgb_preview(rgb)

    return {
        "classification": classification,
        "ndvi": summarize_index(ndvi),
        "ndwi": summarize_index(ndwi),
    }