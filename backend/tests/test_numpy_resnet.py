import numpy as np
import pytest

from app.classification.numpy_resnet import (BN_EPS, NumpyResNet18, conv2d, fold_state_dict, load_params,
                                             save_params)


def naive_conv(x, w, b, stride, pad):
    n, c, h, wd = x.shape
    o, _, kh, kw = w.shape
    xp = np.pad(x, ((0, 0), (0, 0), (pad, pad), (pad, pad)))
    ho, wo = (h + 2 * pad - kh) // stride + 1, (wd + 2 * pad - kw) // stride + 1
    out = np.zeros((n, o, ho, wo))
    for i in range(ho):
        for j in range(wo):
            patch = xp[:, :, i * stride:i * stride + kh, j * stride:j * stride + kw]
            out[:, :, i, j] = np.tensordot(patch, w, axes=([1, 2, 3], [1, 2, 3])) + b
    return out


@pytest.mark.parametrize("k,stride,pad", [(3, 1, 1), (3, 2, 1), (7, 2, 3), (1, 2, 0)])
def test_conv_matches_naive_loops(k, stride, pad):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(2, 3, 16, 16)).astype(np.float32)
    w = rng.normal(size=(4, 3, k, k)).astype(np.float32)
    b = rng.normal(size=4).astype(np.float32)
    assert np.allclose(conv2d(x, w, b, stride, pad), naive_conv(x, w, b, stride, pad), atol=1e-4)


def random_state(rng, in_ch=5, n_classes=10):
    """A torchvision-resnet18-shaped state_dict with random values (conv1 has in_ch channels)."""
    s = {"conv1.weight": rng.normal(size=(64, in_ch, 7, 7)) * 0.1}

    def bn(name, c):
        s[name + ".weight"] = rng.uniform(0.5, 1.5, c)
        s[name + ".bias"] = rng.normal(0, 0.1, c)
        s[name + ".running_mean"] = rng.normal(0, 0.1, c)
        s[name + ".running_var"] = rng.uniform(0.5, 2.0, c)

    bn("bn1", 64)
    cin = 64
    for layer, cout in zip((1, 2, 3, 4), (64, 128, 256, 512)):
        for blk in range(2):
            p = f"layer{layer}.{blk}"
            first_in = cin if blk == 0 else cout
            s[p + ".conv1.weight"] = rng.normal(size=(cout, first_in, 3, 3)) * 0.05
            bn(p + ".bn1", cout)
            s[p + ".conv2.weight"] = rng.normal(size=(cout, cout, 3, 3)) * 0.05
            bn(p + ".bn2", cout)
            if blk == 0 and layer > 1:
                s[p + ".downsample.0.weight"] = rng.normal(size=(cout, cin, 1, 1)) * 0.05
                bn(p + ".downsample.1", cout)
        cin = cout
    s["fc.weight"] = rng.normal(size=(n_classes, 512)) * 0.05
    s["fc.bias"] = rng.normal(size=n_classes) * 0.05
    return s


def test_bn_fold_equals_conv_then_batchnorm():
    rng = np.random.default_rng(1)
    state = random_state(rng)
    folded = fold_state_dict(state)
    x = rng.normal(size=(1, 5, 20, 20)).astype(np.float32)
    seq = conv2d(x, state["conv1.weight"].astype(np.float32), np.zeros(64, np.float32), 2, 3)
    scale = state["bn1.weight"] / np.sqrt(state["bn1.running_var"] + BN_EPS)
    seq = (seq - state["bn1.running_mean"][None, :, None, None]) * scale[None, :, None, None] \
        + state["bn1.bias"][None, :, None, None]
    assert np.allclose(conv2d(x, folded["conv1.w"], folded["conv1.b"], 2, 3), seq, atol=1e-4)


def test_network_shapes_determinism_and_batching(tmp_path):
    rng = np.random.default_rng(2)
    params = fold_state_dict(random_state(rng))
    net = NumpyResNet18(params)
    x = rng.normal(size=(5, 5, 64, 64)).astype(np.float32)
    z = net.logits(x)
    assert z.shape == (5, 10) and np.isfinite(z).all()
    assert np.array_equal(z, net.logits(x))                      # deterministic
    p1, c1 = net.predict(x, batch=2)
    p2, c2 = net.predict(x, batch=5)
    assert np.array_equal(p1, p2) and np.allclose(c1, c2) and ((c1 > 0) & (c1 <= 1)).all()
    save_params(tmp_path / "m.npz", params)
    assert np.array_equal(NumpyResNet18(load_params(tmp_path / "m.npz")).logits(x), z)


def test_empty_input():
    net = NumpyResNet18(fold_state_dict(random_state(np.random.default_rng(3))))
    p, c = net.predict(np.empty((0, 5, 64, 64), np.float32))
    assert len(p) == 0 and len(c) == 0
