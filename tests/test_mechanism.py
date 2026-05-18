import math
import random

import pytest

from ulu import DelegatedUnderwriting
from ulu.errors import InfeasibleOperationError, InvariantViolationError, ProtocolError, UnknownUserError


def build_network() -> DelegatedUnderwriting:
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    m.add_user("a", "b", 20.0)
    m.add_user("b", "c", 10.0)
    return m


def test_conservation_under_delegation():
    m = build_network()
    lhs = m.total_credit_limit()
    rhs = sum(m.base_budget[s] for s in m.seeds) + sum(m.earned.values())
    assert lhs == pytest.approx(rhs)


def test_revocation_solvency_boundary():
    m = build_network()
    m.principal["c"] = 7.0
    need_b = m.required_delegation("b")
    m.revoke("a", "b", need_b)
    with pytest.raises(InfeasibleOperationError):
        m.revoke("a", "b", max(0.0, need_b - 0.1))


def test_default_propagation_and_seed_absorption():
    m = build_network()
    m.earned["c"] = 2.0
    m.earned["b"] = 1.0
    m.earned["a"] = 3.0
    m.earned["s"] = 2.0
    m.principal["c"] = 12.0
    before_total = m.total_credit_limit()
    m.default("c")
    after_total = m.total_credit_limit()
    assert m.principal["c"] == 0.0
    assert after_total == pytest.approx(before_total - 12.0)
    m.assert_invariants()


def test_sponsor_path_total_credit_limit_decreases_by_principal():
    m = build_network()
    m.earned["a"] = 2.0
    m.earned["b"] = 1.0
    m.principal["c"] = 5.0
    before_total = m.total_credit_limit()
    m.default("c")
    after_total = m.total_credit_limit()
    assert m.principal["c"] == 0.0
    assert after_total == pytest.approx(before_total - 5.0)
    m.assert_invariants()


def test_protocol_premium_break_even_logic():
    m = build_network()
    d = 0.2
    t = 2.0
    r_star = m.protocol_break_even_rate(d, t)
    assert r_star == pytest.approx(d / ((1 - d) * t))


def test_repay_then_default_bound():
    m = build_network()
    q = m.quote_loan(
        borrower="c",
        principal=4.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.5,
        max_delegation_rate=0.0,
    )
    delta_g = 1.0
    m.repay("c", delta_g)
    upper_bound = delta_g - q.protocol_premium
    assert upper_bound <= 0.0


def test_delegation_utilization_formula():
    m = build_network()
    util = m.seed_delegation_utilization()
    expected = m.delegation[("s", "a")] / m.budget("s")
    assert util == pytest.approx(expected)


def test_local_and_downstream_buffers():
    m = build_network()
    m.earned["b"] = 6.0
    m.principal["b"] = 1.0
    m.earned["c"] = 3.0
    b_b = m.local_buffer("b")
    b_c = m.local_buffer("c")
    assert b_b == pytest.approx(5.0)
    assert b_c == pytest.approx(3.0)
    db = m.downstream_buffers("c")
    assert db[("s", "a")] == pytest.approx(m.local_buffer("a") + b_b + b_c)
    assert db[("a", "b")] == pytest.approx(b_b + b_c)
    assert db[("b", "c")] == pytest.approx(b_c)


def test_feasibility_and_locked_delegation():
    m = build_network()
    m.earned["c"] = 2.0
    locked = m.locked_delegation("c", principal=6.0)
    assert locked[("b", "c")] == pytest.approx(4.0)
    with pytest.raises(InfeasibleOperationError):
        m.locked_delegation("c", principal=200.0)


def test_delegation_premium_budget_balanced():
    m = build_network()
    q = m.quote_loan(
        borrower="c",
        principal=5.0,
        term=1.5,
        default_probability=0.2,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    assert math.isclose(
        q.delegation_premium,
        sum(q.delegation_payouts.values()),
        rel_tol=1e-12,
    )


def test_persistence_round_trip(tmp_path):
    m = build_network()
    m.earned["a"] = 1.2
    m.principal["c"] = 3.4
    path = tmp_path / "state.json"
    m.save_json(path)
    restored = DelegatedUnderwriting.load_json(path)
    assert restored.to_dict() == m.to_dict()
    restored.assert_invariants()


def test_persistence_rejects_wrong_schema_version():
    m = build_network()
    payload = m.to_dict()
    payload["schema_version"] = 999
    with pytest.raises(ProtocolError):
        DelegatedUnderwriting.from_dict(payload)


def test_persistence_rejects_structurally_invalid_state():
    m = build_network()
    payload = m.to_dict()
    payload["state"]["parent"]["s"] = "a"
    with pytest.raises(InvariantViolationError):
        DelegatedUnderwriting.from_dict(payload)


def test_invalid_unknown_user_errors_are_explicit():
    m = build_network()
    with pytest.raises(UnknownUserError):
        m.credit_limit("ghost")
    with pytest.raises(UnknownUserError):
        m.repay("ghost", 1.0)


def test_invalid_inputs_fail_fast():
    m = build_network()
    with pytest.raises(ProtocolError):
        m.add_seed("s2", 0.0)
    with pytest.raises(ProtocolError):
        m.quote_loan(
            "c",
            principal=-1.0,
            term=1.0,
            default_probability=0.2,
            protocol_rate=0.1,
            max_delegation_rate=0.1,
        )
    with pytest.raises(ProtocolError):
        m.quote_loan(
            "c",
            principal=1.0,
            term=0.0,
            default_probability=0.2,
            protocol_rate=0.1,
            max_delegation_rate=0.1,
        )
    with pytest.raises(ProtocolError):
        m.quote_loan(
            "c",
            principal=1.0,
            term=1.0,
            default_probability=1.2,
            protocol_rate=0.1,
            max_delegation_rate=0.1,
        )


def test_end_to_end_originate_repay_default_revoke_flow():
    m = DelegatedUnderwriting()
    m.add_seed("s", 200.0)
    m.add_user("s", "a", 70.0)
    m.add_user("a", "b", 30.0)

    quote = m.originate_loan(
        "b",
        principal=10.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    assert quote.total_interest > 0
    assert m.principal["b"] == 10.0

    m.repay("b", 2.0)
    m.principal["b"] = 6.0
    pre = m.total_credit_limit()
    m.default("b")
    post = m.total_credit_limit()
    assert post == pytest.approx(pre - 6.0)

    req = m.required_delegation("b")
    m.revoke("a", "b", req)
    m.assert_invariants()


def test_randomized_credit_conservation_under_redelegation_like_operations():
    rng = random.Random(7)
    m = DelegatedUnderwriting()
    m.add_seed("s", 300.0)
    m.add_user("s", "a", 120.0)
    m.add_user("a", "b", 80.0)
    m.add_user("b", "c", 60.0)

    for _ in range(40):
        u = rng.choice(["s", "a", "b", "c"])
        m.repay(u, rng.random())

        if rng.random() < 0.5:
            lower = max(
                m.required_delegation("b"),
                m.outgoing_delegation("b") - m.earned["b"],
            )
            upper = m.delegation[("a", "b")]
            if lower <= upper:
                new_ab = rng.uniform(lower, upper)
                m.revoke("a", "b", new_ab)

        lhs = m.total_credit_limit()
        rhs = sum(m.base_budget[s] for s in m.seeds) + sum(m.earned.values())
        assert lhs == pytest.approx(rhs)
        m.assert_invariants()


def test_empty_state_requires_at_least_one_seed():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.assert_invariants()


def test_non_seed_with_no_children():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 30.0)
    assert m.children["a"] == []
    assert m.required_delegation("a") == 0.0
    m.assert_invariants()


def test_borrower_with_no_active_loan_can_quote():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    q = m.quote_loan(
        borrower="a",
        principal=10.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    assert q.total_interest > 0.0
    m.assert_invariants()


def test_default_where_earned_absorbs_all_loss_before_reaching_seed():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    m.add_user("a", "b", 20.0)
    m.earned["b"] = 15.0
    m.principal["b"] = 10.0
    before = m.total_credit_limit()
    m.default("b")
    after = m.total_credit_limit()
    assert after == pytest.approx(before - 10.0)
    assert m.earned["b"] == 5.0
    assert m.principal["b"] == 0.0
    assert m.delegation[("a", "b")] == 20.0
    assert m.delegation[("s", "a")] == 40.0
    m.assert_invariants()


def test_revocation_at_exact_boundary_is_allowed():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    m.add_user("a", "b", 20.0)
    m.principal["b"] = 5.0
    need = m.required_delegation("b")
    m.revoke("a", "b", need)
    m.assert_invariants()


def test_credit_limit_zero_prevents_loan():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    m.add_user("a", "b", 20.0)
    m.add_user("b", "c", 20.0)
    m.originate_loan(
        borrower="c",
        principal=20.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    with pytest.raises(InfeasibleOperationError):
        m.quote_loan(
            borrower="c",
            principal=1.0,
            term=1.0,
            default_probability=0.1,
            protocol_rate=0.2,
            max_delegation_rate=0.1,
        )


def test_theorem_3_total_credit_limit_decreases_by_principal():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 50.0)
    m.add_user("a", "b", 30.0)
    m.earned["b"] = 10.0
    m.earned["a"] = 5.0
    m.earned["s"] = 5.0
    m.principal["b"] = 35.0
    before_total = m.total_credit_limit()
    m.default("b")
    assert m.principal["b"] == 0.0
    assert m.total_credit_limit() == pytest.approx(before_total - 35.0)
    m.assert_invariants()


def test_theorem_7_locked_delegation_with_partial_downstream_buffer():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    m.add_user("a", "b", 20.0)
    m.earned["b"] = 5.0
    m.principal["b"] = 2.0
    locked = m.locked_delegation("b", principal=8.0)
    # b can absorb 3 (earned 5 - principal 2); remaining 5 must be backed by delegation
    assert locked[("a", "b")] == pytest.approx(5.0)
    assert locked[("s", "a")] == pytest.approx(5.0)


def test_repay_then_default_with_delta_g_exceeds_protocol_premium():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    q = m.quote_loan(
        borrower="a",
        principal=5.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.05,
        max_delegation_rate=0.0,
    )
    m.repay("a", 10.0)
    upper_bound = 10.0 - q.protocol_premium
    assert upper_bound > 0.0


def test_protocol_break_even_rate_exactness():
    m = DelegatedUnderwriting()
    for d, t in [(0.1, 1.0), (0.25, 2.0), (0.5, 0.5)]:
        r = m.protocol_break_even_rate(d, t)
        lhs = (1 - d) * r * t
        assert lhs == pytest.approx(d)


def test_delegation_premium_decreases_with_high_utilization():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 10.0)
    q1 = m.quote_loan(
        borrower="a",
        principal=1.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    m.add_user("s", "b", 80.0)
    q2 = m.quote_loan(
        borrower="a",
        principal=1.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    assert q2.delegation_rate < q1.delegation_rate


def test_default_on_borrower_with_zero_principal_raises():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    with pytest.raises(InfeasibleOperationError):
        m.default("a")


def test_revoke_on_seed_child_edge_with_increase_checks_credit_limit():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 30.0)
    m.revoke("s", "a", 35.0)
    assert m.delegation[("s", "a")] == 35.0
    with pytest.raises(InfeasibleOperationError):
        m.revoke("s", "a", 200.0)
    m.assert_invariants()


def test_persistence_with_complex_state(tmp_path):
    m = DelegatedUnderwriting()
    m.add_seed("s1", 100.0)
    m.add_seed("s2", 200.0)
    m.add_user("s1", "a", 40.0)
    m.add_user("a", "b", 20.0)
    m.add_user("s2", "c", 80.0)
    m.earned["a"] = 5.0
    m.earned["b"] = 3.0
    m.principal["b"] = 10.0
    path = tmp_path / "state.json"
    m.save_json(path)
    restored = DelegatedUnderwriting.load_json(path)
    assert restored.to_dict() == m.to_dict()
    restored.assert_invariants()


def test_quote_does_not_mutate_principal():
    m = DelegatedUnderwriting()
    m.add_seed("s", 100.0)
    m.add_user("s", "a", 40.0)
    m.quote_loan(
        borrower="a",
        principal=10.0,
        term=1.0,
        default_probability=0.1,
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    assert m.principal["a"] == 0.0
    m.assert_invariants()
