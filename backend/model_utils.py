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


def analyze_tif(file_bytes: bytes) -> tuple:
    bands = load_bands_from_bytes(file_bytes)
    ndvi = compute_ndvi(bands)
    ndwi = compute_ndwi(bands)
    rgb = get_rgb_preview(bands)

    classification = classify_rgb_preview(rgb)

    result = {
        "classification": classification,
        "ndvi": summarize_index(ndvi),
        "ndwi": summarize_index(ndwi),
    }
    return result, bands

def generate_answer(analysis: dict, question: str, bands: np.ndarray) -> dict:
    cls = analysis["classification"]["class"]
    conf = analysis["classification"]["confidence"]
    ndvi_mean = analysis["ndvi"]["mean"]
    ndwi_mean = analysis["ndwi"]["mean"]

    if ndvi_mean > 0.3:
        veg_level = "high"
    elif ndvi_mean > 0.1:
        veg_level = "moderate"
    else:
        veg_level = "low"

    water_present = ndwi_mean > 0
    focus = "water" if water_present else "vegetation"

    answer = (
        f"This image is classified as '{cls}' with {conf*100:.1f}% confidence. "
        f"The NDVI value is {ndvi_mean:.3f}, indicating {veg_level} vegetation presence. "
    )
    if water_present:
        answer += f"The NDWI value ({ndwi_mean:.3f}) suggests water is likely present in this region."
    else:
        answer += f"The NDWI value ({ndwi_mean:.3f}) suggests no significant water presence."

    evidence_region = get_evidence_region(bands, focus=focus)

    return {
        "answer": answer,
        "evidence": {
            "class": cls,
            "confidence": conf,
            "ndvi_mean": ndvi_mean,
            "ndwi_mean": ndwi_mean,
            "region": evidence_region,
        },
        "question": question,
    }
def get_evidence_region(bands: np.ndarray, focus: str = "vegetation") -> dict:
    """
    Splits image into a 4x4 grid, computes NDVI/NDWI per cell,
    returns the pixel bounding box of the most relevant cell.
    """
    from preprocessing import compute_ndvi, compute_ndwi

    ndvi_full = compute_ndvi(bands)
    ndwi_full = compute_ndwi(bands)

    h, w = ndvi_full.shape
    grid_size = 4
    cell_h, cell_w = h // grid_size, w // grid_size

    best_score = -999
    best_box = None

    for row in range(grid_size):
        for col in range(grid_size):
            y0, y1 = row * cell_h, (row + 1) * cell_h
            x0, x1 = col * cell_w, (col + 1) * cell_w

            if focus == "water":
                score = ndwi_full[y0:y1, x0:x1].mean()
            else:
                score = ndvi_full[y0:y1, x0:x1].mean()

            if score > best_score:
                best_score = score
                best_box = {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}

    return {"box": best_box, "focus": focus, "score": round(float(best_score), 4)}