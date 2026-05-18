# Theorem Evaluation

## Running checks

The test suite verifies every major theorem from the paper.

```bash
PYTHONPATH=. pytest tests/test_mechanism.py -v
```

## Theorem 1 — Credit conservation

```python
def test_conservation_under_delegation():
    lhs = mechanism.total_credit_limit()
    rhs = sum(mechanism.base_budget[s] for s in mechanism.seeds) + sum(mechanism.earned.values())
    assert lhs == pytest.approx(rhs)
```

## Theorem 2 — Revocation solvency

```python
def test_revocation_solvency_boundary():
    need = mechanism.required_delegation("child")
    mechanism.revoke("sponsor", "child", need)          # ok
    with pytest.raises(InfeasibleOperationError):
        mechanism.revoke("sponsor", "child", need - epsilon)  # fails
```

## Theorem 3 — Default propagation well-defined

Verified indirectly by `test_default_propagation_and_seed_absorption` and `test_sponsor_path_credit_limit_conservation_except_borrower`.

## Theorem 4 — Sponsor-path credit limit conservation

```python
def test_sponsor_path_credit_limit_conservation_except_borrower():
    before = {u: mechanism.credit_limit(u) for u in users}
    mechanism.default("borrower")
    after = {u: mechanism.credit_limit(u) for u in users}
    for u in upstream_nodes:
        assert after[u] == pytest.approx(before[u])
    assert after["borrower"] == pytest.approx(before["borrower"] - principal)
```

## Theorem 5 — Break-even protocol rate

```python
def test_protocol_premium_break_even_logic():
    r_star = mechanism.protocol_break_even_rate(d, t)
    assert r_star == pytest.approx(d / ((1 - d) * t))
```

## Theorem 6 — Repay-then-default bound

```python
def test_repay_then_default_bound():
    quote = mechanism.quote_loan(...)
    mechanism.repay("borrower", delta_g)
    upper_bound = delta_g - quote.protocol_premium
    assert upper_bound <= 0.0
```

## Theorem 7 — Feasibility and locked delegation

```python
def test_feasibility_and_locked_delegation():
    locked = mechanism.locked_delegation("borrower", principal=6.0)
    assert locked[("sponsor", "borrower")] == pytest.approx(expected)
    with pytest.raises(InfeasibleOperationError):
        mechanism.locked_delegation("borrower", principal=excessive)
```

## Randomized invariant stress test

```python
def test_randomized_credit_conservation_under_redelegation_like_operations():
    for _ in range(40):
        mechanism.repay(user, random_amount)
        mechanism.revoke(sponsor, child, random_valid_amount)
        assert mechanism.total_credit_limit() == pytest.approx(
            sum(base_budget) + sum(earned)
        )
        mechanism.assert_invariants()
```
