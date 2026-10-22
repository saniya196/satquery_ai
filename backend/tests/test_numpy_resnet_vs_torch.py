"""Equivalence with real torch. Skipped automatically where torch cannot be imported (e.g. blocked DLLs)."""
import numpy as np
import pytest

try:
    import torchvision
    import torch
    import torch.nn as nn
except Exception:          # ImportError, or OSError from Application Control
    torch = None

from app.classification.numpy_resnet import NumpyResNet18, fold_state_dict

pytestmark = pytest.mark.skipif(torch is None, reason="torch not importable on this machine")


def test_numpy_resnet_matches_torchvision_resnet18():
    torch.manual_seed(0)
    m = torchvision.models.resnet18(weights=None)
    m.conv1 = nn.Conv2d(5, 64, 7, 2, 3, bias=False)
    m.maxpool = nn.Identity()
    m.fc = nn.Linear(512, 10)
    for mod in m.modules():
        if isinstance(mod, nn.BatchNorm2d):
            mod.weight.data.uniform_(0.5, 1.5); mod.bias.data.normal_(0, 0.3)
            mod.running_mean.normal_(0, 0.3); mod.running_var.uniform_(0.5, 2.0)
    m.eval()
    x = torch.randn(6, 5, 64, 64)
    with torch.no_grad():
        ref = m(x).numpy()
    out = NumpyResNet18(fold_state_dict({k: v.numpy() for k, v in m.state_dict().items()})).logits(x.numpy())
    assert np.abs(out - ref).max() < 1e-4
    assert (out.argmax(1) == ref.argmax(1)).all()
