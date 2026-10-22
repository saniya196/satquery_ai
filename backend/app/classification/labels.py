"""Land-cover labels, product-class mapping, and numpy-only metrics (no torch needed).

Trained on EuroSAT (Sentinel-2 L1C, 64x64 px patches, 10 classes). EuroSAT has NO bare-soil class,
so 'bare soil' can never come from this model; it must be labelled index-derived if shown at all.
"""
import numpy as np

# Order of torchgeo.datasets.EuroSAT.classes (label index = position). The notebook asserts this.
EUROSAT_CLASSES = ["AnnualCrop", "Forest", "HerbaceousVegetation", "Highway", "Industrial",
                   "Pasture", "PermanentCrop", "Residential", "River", "SeaLake"]

PRODUCT_CLASSES = ["vegetation", "agricultural_land", "built_up", "water"]

PRODUCT_MAP = {
    "AnnualCrop": "agricultural_land", "PermanentCrop": "agricultural_land", "Pasture": "agricultural_land",
    "Forest": "vegetation", "HerbaceousVegetation": "vegetation",
    "Highway": "built_up", "Industrial": "built_up", "Residential": "built_up",
    "River": "water", "SeaLake": "water",
}

# Sentinel-2 bands the model uses, and the logical names SceneData/provider use, in channel order.
BANDS = ("B02", "B03", "B04", "B08", "B11")
LOGICAL_BANDS = ("blue", "green", "red", "nir", "swir1")
TILE = 64            # EuroSAT patch size in pixels (10 m -> 640 m)
SCALE = 10000.0      # DN -> reflectance


def product_index(eurosat_idx):
    """Map EuroSAT label indices (int or array) to PRODUCT_CLASSES indices."""
    lut = np.array([PRODUCT_CLASSES.index(PRODUCT_MAP[c]) for c in EUROSAT_CLASSES])
    return lut[np.asarray(eurosat_idx)]


def confusion_matrix(y_true, y_pred, n_classes):
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    np.add.at(cm, (np.asarray(y_true), np.asarray(y_pred)), 1)
    return cm


def metrics_from_cm(cm, names):
    cm = np.asarray(cm)
    tp = np.diag(cm).astype(float)
    support, predicted = cm.sum(axis=1).astype(float), cm.sum(axis=0).astype(float)
    prec = np.divide(tp, predicted, out=np.zeros_like(tp), where=predicted > 0)
    rec = np.divide(tp, support, out=np.zeros_like(tp), where=support > 0)
    f1 = np.divide(2 * prec * rec, prec + rec, out=np.zeros_like(tp), where=(prec + rec) > 0)
    return {
        "accuracy": float(tp.sum() / cm.sum()),
        "macro_precision": float(prec.mean()), "macro_recall": float(rec.mean()), "macro_f1": float(f1.mean()),
        "per_class": {n: {"precision": float(prec[i]), "recall": float(rec[i]), "f1": float(f1[i]),
                          "support": int(support[i])} for i, n in enumerate(names)},
    }


def expected_calibration_error(confidence, correct, n_bins=10):
    """ECE + per-bin table. Low ECE = confidence matches accuracy. Still NOT scientific certainty."""
    conf = np.asarray(confidence, dtype=float)
    ok = np.asarray(correct, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece, table = 0.0, []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (conf > lo) & (conf <= hi) if i else (conf >= lo) & (conf <= hi)
        n = int(m.sum())
        if n:
            c, a = float(conf[m].mean()), float(ok[m].mean())
            ece += n / len(conf) * abs(a - c)
        else:
            c = a = None
        table.append({"lo": float(lo), "hi": float(hi), "count": n, "mean_confidence": c, "accuracy": a})
    return float(ece), table


def normalise(cube, mean, std):
    """cube: (C,H,W) reflectance. mean/std: per-band, same order as BANDS."""
    mean = np.asarray(mean, dtype=np.float32).reshape(-1, 1, 1)
    std = np.asarray(std, dtype=np.float32).reshape(-1, 1, 1)
    return (np.asarray(cube, dtype=np.float32) - mean) / std
