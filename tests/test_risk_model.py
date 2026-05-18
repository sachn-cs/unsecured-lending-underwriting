from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split

from ulu import DelegatedUnderwriting
from ulu.risk_model import OptimizedGreedyWeightedRiskModel, quote_with_estimated_default


def dataset() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x, y = make_classification(
        n_samples=250,
        n_features=10,
        n_informative=6,
        n_redundant=1,
        random_state=7,
    )
    x_train, x_val, y_train, y_val = train_test_split(
        x,
        y,
        test_size=0.3,
        random_state=7,
        stratify=y,
    )
    return x_train, x_val, y_train, y_val


def test_risk_model_predicts_probabilities_in_unit_interval() -> None:
    x_train, x_val, y_train, y_val = dataset()
    model = OptimizedGreedyWeightedRiskModel()
    model.fit(x_train, y_train, x_val, y_val)

    probs = model.predict_default_probability(x_val[:8])
    assert probs.shape == (8,)
    assert np.all(probs >= 0.0)
    assert np.all(probs <= 1.0)


def test_mechanism_quote_uses_estimated_default_probability() -> None:
    x_train, x_val, y_train, y_val = dataset()
    risk = OptimizedGreedyWeightedRiskModel()
    risk.fit(x_train, y_train, x_val, y_val)

    mech = DelegatedUnderwriting()
    mech.add_seed("s", 100.0)
    mech.add_user("s", "u", 30.0)

    quote = quote_with_estimated_default(
        mech,
        borrower="u",
        principal=5.0,
        term=1.0,
        default_probability_estimator=risk,
        feature_row=x_val[:1],
        protocol_rate=0.2,
        max_delegation_rate=0.1,
    )
    assert 0.0 < quote.default_probability < 1.0
