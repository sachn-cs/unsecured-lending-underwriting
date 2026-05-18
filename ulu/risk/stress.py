"""Monte Carlo correlated default simulation for portfolio stress testing."""

from __future__ import annotations

import math
import random


class StressTestEngine:
    """Runs Monte Carlo simulations to estimate tail risk."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)

    def _inv_norm_cdf(self, p: float) -> float:
        """Approximate inverse CDF for standard normal (Beasley-Springer-Moro)."""
        if p <= 0.0:
            return -5.0
        if p >= 1.0:
            return 5.0
        a1 = -3.969683028665376e1
        a2 = 2.209460984245205e2
        a3 = -2.759285104469687e2
        a4 = 1.383577518672690e2
        a5 = -3.066479806614716e1
        a6 = 2.506628277459239e0
        b1 = -5.447609879822406e1
        b2 = 1.615858368580409e2
        b3 = -1.556989798598866e2
        b4 = 6.680131368771878e1
        b5 = -1.328068155288572e1
        c1 = -7.784894002430293e-3
        c2 = -3.223964580411365e-1
        c3 = -2.400758277161838e0
        c4 = -2.549732539343734e0
        c5 = 4.374664141464968e0
        c6 = 2.938163982698783e0
        d1 = 7.784695709041462e-3
        d2 = 3.224671290700398e-1
        d3 = 2.445134137142996e0
        d4 = 3.754408661907416e0
        p_low = 0.02425
        p_high = 1.0 - p_low
        if p < p_low:
            q = math.sqrt(-2.0 * math.log(p))
            return (((((c1 * q + c2) * q + c3) * q + c4) * q + c5) * q + c6) / (
                (((d1 * q + d2) * q + d3) * q + d4) * q + 1.0
            )
        if p <= p_high:
            q = p - 0.5
            r = q * q
            return (
                (((((a1 * r + a2) * r + a3) * r + a4) * r + a5) * r + a6)
                * q
                / (((((b1 * r + b2) * r + b3) * r + b4) * r + b5) * r + 1.0)
            )
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c1 * q + c2) * q + c3) * q + c4) * q + c5) * q + c6) / (
            (((d1 * q + d2) * q + d3) * q + d4) * q + 1.0
        )

    def simulate_correlated_defaults(
        self,
        borrowers: list[dict],
        correlation: float,
        n_simulations: int = 10_000,
    ) -> dict:
        if not borrowers:
            return {"expected_loss": 0.0, "var_95": 0.0, "var_99": 0.0}
        if not (0.0 <= correlation <= 1.0):
            raise ValueError("correlation must be in [0, 1]")

        losses: list[float] = []
        rho = correlation
        for _ in range(n_simulations):
            systemic_u = self.rng.random()
            systemic_z = self._inv_norm_cdf(systemic_u)
            total_loss = 0.0
            for b in borrowers:
                p = b["default_probability"]
                principal = b["principal"]
                idio_u = self.rng.random()
                idio_z = self._inv_norm_cdf(idio_u)
                correlated_z = math.sqrt(rho) * systemic_z + math.sqrt(1.0 - rho) * idio_z
                if correlated_z <= self._inv_norm_cdf(p):
                    total_loss += principal
            losses.append(total_loss)

        losses.sort()
        expected = sum(losses) / len(losses)
        n = len(losses)
        var_95 = losses[int(0.95 * n) - 1] if n >= 20 else losses[-1]
        var_99 = losses[int(0.99 * n) - 1] if n >= 100 else losses[-1]
        return {"expected_loss": expected, "var_95": var_95, "var_99": var_99}
