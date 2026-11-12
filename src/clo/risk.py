"""Loss statistics: expected loss, VaR, expected shortfall, bootstrap intervals."""
from __future__ import annotations

import numpy as np


def var(loss: np.ndarray, q: float = 0.995) -> float:
    """q-quantile of the loss (lower empirical quantile, no interpolation)."""
    x = np.sort(np.asarray(loss, dtype=float))
    k = int(np.ceil(q * len(x))) - 1
    return float(x[k])


def es(loss: np.ndarray, q: float = 0.995) -> float:
    """Mean of the worst (1 - q) share of outcomes."""
    x = np.sort(np.asarray(loss, dtype=float))
    m = max(int(round((1.0 - q) * len(x))), 1)
    return float(x[-m:].mean())


def summary(loss: np.ndarray, q: float = 0.995) -> dict[str, float]:
    loss = np.asarray(loss, dtype=float)
    hit = loss > 1e-9
    return {
        "el": float(loss.mean()),
        "p_loss": float(hit.mean()),
        "loss_given_loss": float(loss[hit].mean()) if hit.any() else 0.0,
        "q96": var(loss, 0.96),
        "var": var(loss, q),
        "es": es(loss, q),
        "max": float(loss.max()),
    }


def bootstrap_ci(loss: np.ndarray, stat, n_boot: int = 1000, level: float = 0.90,
                 seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    loss = np.asarray(loss, dtype=float)
    vals = np.array([stat(loss[rng.integers(0, len(loss), len(loss))]) for _ in range(n_boot)])
    a = (1.0 - level) / 2.0
    return float(np.quantile(vals, a)), float(np.quantile(vals, 1.0 - a))
