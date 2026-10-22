"""Check the exported numpy model on THIS machine, using real EuroSAT test tiles saved by the notebook.

Run from backend/:   python scripts\\verify_model.py            (uses ..\\models)
                     python scripts\\verify_model.py C:\\path\\to\\models
No torch needed. Prints: parity with torch, accuracy on the saved real tiles, speed.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.classification.labels import EUROSAT_CLASSES, product_index  # noqa: E402
from app.classification.numpy_resnet import NumpyResNet18, load_params  # noqa: E402

d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "models"
net = NumpyResNet18(load_params(d / "landcover_resnet18.npz"))
ref = np.load(d / "reference_logits.npz")
x, torch_logits, y = ref["x"], ref["logits"], ref["y"]

t = time.time()
out = net.logits(x)
dt = (time.time() - t) / len(x)
diff = float(np.abs(out - torch_logits).max())
agree = float((out.argmax(1) == torch_logits.argmax(1)).mean())
pred = out.argmax(1)
print(f"model dir            : {d}")
print(f"tiles checked        : {len(x)} real EuroSAT test tiles (saved by the notebook)")
print(f"max |logit diff|     : {diff:.2e}   (vs torch; must be tiny)")
print(f"prediction agreement : {agree:.0%}     (vs torch; must be 100%)")
print(f"10-class accuracy    : {(pred == y).mean():.1%} on these {len(y)} tiles")
print(f"product-class acc.   : {(product_index(pred) == product_index(y)).mean():.1%}")
print(f"speed                : {dt * 1000:.0f} ms per 64x64 tile on this CPU")
wrong = [(EUROSAT_CLASSES[a], EUROSAT_CLASSES[b]) for a, b in zip(y, pred) if a != b]
print("mistakes (true -> predicted):", wrong if wrong else "none")
ok = diff < 1e-3 and agree == 1.0
print("RESULT:", "OK - numpy model matches torch" if ok else "PROBLEM - do not use this export")
sys.exit(0 if ok else 1)
