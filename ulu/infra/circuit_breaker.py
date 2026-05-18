"""Circuit breaker factory for external API integrations.

Provides pre-configured breakers for KYC, credit bureau, and blockchain
endpoints to prevent cascade failures under load.
"""

from __future__ import annotations

import pybreaker


def create_circuit_breaker(name: str) -> pybreaker.CircuitBreaker:
    """Returns a CircuitBreaker with standard ULU settings.

    Default: 5 failures within 30s opens the circuit for 60s.
    """
    return pybreaker.CircuitBreaker(
        fail_max=5,
        reset_timeout=60,
        expected_exception=(Exception,),
        name=name,
    )


kyc_breaker = create_circuit_breaker("kyc")
bureau_breaker = create_circuit_breaker("bureau")
blockchain_breaker = create_circuit_breaker("blockchain")
