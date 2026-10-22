"""ResNet18 inference in pure numpy (no torch), for machines where PyTorch's DLLs are blocked.

Matches the trained model: torchvision resnet18 with a 5-channel conv1, maxpool replaced by Identity,
10-way fc. BatchNorm (eval mode) is folded into the preceding conv, so weights are just conv w/b + fc.
Verified against torch in tests/test_numpy_resnet_vs_torch.py and by the Colab export cell.
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

BN_EPS = 1e-5
LAYERS = (1, 2, 3, 4)
BLOCKS_PER_LAYER = 2


def conv2d(x, w, b, stride=1, pad=0):
    """x (N,C,H,W), w (O,C,kh,kw), b (O,) -> (N,O,Ho,Wo). im2col + matmul."""
    n, c, _, _ = x.shape
    o, _, kh, kw = w.shape
    if pad:
        x = np.pad(x, ((0, 0), (0, 0), (pad, pad), (pad, pad)))
    win = sliding_window_view(x, (kh, kw), axis=(2, 3))[:, :, ::stride, ::stride]
    ho, wo = win.shape[2], win.shape[3]
    cols = win.transpose(0, 2, 3, 1, 4, 5).reshape(n * ho * wo, c * kh * kw)
    out = cols @ w.reshape(o, -1).T + b
    return np.ascontiguousarray(out.reshape(n, ho, wo, o).transpose(0, 3, 1, 2), dtype=np.float32)


def _relu(x):
    return np.maximum(x, 0.0)


def fold_state_dict(state):
    """torch state_dict (as numpy arrays) -> folded params {'<conv>.w', '<conv>.b', 'fc.w', 'fc.b'}."""
    s = {k: np.asarray(v, dtype=np.float64) for k, v in state.items()}
    out = {}

    def fold(conv, bn):
        scale = s[bn + ".weight"] / np.sqrt(s[bn + ".running_var"] + BN_EPS)
        out[conv + ".w"] = (s[conv + ".weight"] * scale[:, None, None, None]).astype(np.float32)
        out[conv + ".b"] = (s[bn + ".bias"] - s[bn + ".running_mean"] * scale).astype(np.float32)

    fold("conv1", "bn1")
    for layer in LAYERS:
        for blk in range(BLOCKS_PER_LAYER):
            p = f"layer{layer}.{blk}"
            fold(p + ".conv1", p + ".bn1")
            fold(p + ".conv2", p + ".bn2")
            if p + ".downsample.0.weight" in s:
                fold(p + ".downsample.0", p + ".downsample.1")
    out["fc.w"] = s["fc.weight"].astype(np.float32)
    out["fc.b"] = s["fc.bias"].astype(np.float32)
    return out


def save_params(path, params):
    np.savez_compressed(path, **params)


def load_params(path):
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


class NumpyResNet18:
    def __init__(self, params):
        self.p = params

    def _block(self, x, name, stride):
        p = self.p
        out = _relu(conv2d(x, p[name + ".conv1.w"], p[name + ".conv1.b"], stride, 1))
        out = conv2d(out, p[name + ".conv2.w"], p[name + ".conv2.b"], 1, 1)
        if name + ".downsample.0.w" in p:
            x = conv2d(x, p[name + ".downsample.0.w"], p[name + ".downsample.0.b"], stride, 0)
        return _relu(out + x)

    def logits(self, x):
        x = np.asarray(x, dtype=np.float32)
        x = _relu(conv2d(x, self.p["conv1.w"], self.p["conv1.b"], 2, 3))   # no maxpool in this model
        for layer in LAYERS:
            for blk in range(BLOCKS_PER_LAYER):
                x = self._block(x, f"layer{layer}.{blk}", 2 if (layer > 1 and blk == 0) else 1)
        return x.mean(axis=(2, 3)) @ self.p["fc.w"].T + self.p["fc.b"]

    def predict(self, x, batch=16):
        """-> (class index, softmax confidence) per sample. Batched to bound memory."""
        preds, confs = [], []
        for i in range(0, len(x), batch):
            z = self.logits(x[i:i + batch]).astype(np.float64)
            z -= z.max(axis=1, keepdims=True)
            e = np.exp(z)
            prob = e / e.sum(axis=1, keepdims=True)
            preds.append(prob.argmax(axis=1))
            confs.append(prob.max(axis=1))
        return (np.concatenate(preds) if preds else np.empty(0, int),
                np.concatenate(confs) if confs else np.empty(0))
