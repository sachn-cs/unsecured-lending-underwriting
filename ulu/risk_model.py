"""Risk-model estimation for default probability based on arXiv:2603.18927."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC

ArrayF = np.ndarray


@dataclass(frozen=True)
class SearchSpace:
    """Defines PSO search bounds and integer dimensions for a base model."""

    bounds: tuple[tuple[float, float], ...]
    int_dims: tuple[int, ...]


@dataclass(frozen=True)
class PsoConfig:
    """Configuration for particle swarm hyperparameter optimization."""

    particles: int = 12
    iterations: int = 20
    inertia: float = 0.7
    c1: float = 1.5
    c2: float = 1.5
    v_max: float = 0.2
    random_state: int = 7


@dataclass(frozen=True)
class GreedyWeightConfig:
    """Configuration for regularized greedy convex weighting."""

    l2_lambda: float = 0.01
    delta: float = 0.02
    iterations: int = 80


class OptimizedGreedyWeightedRiskModel:
    """Implements PSO + greedy weighting + neural meta-learner."""

    def __init__(
        self,
        pso_config: PsoConfig | None = None,
        weight_config: GreedyWeightConfig | None = None,
    ) -> None:
        self.pso_config = pso_config or PsoConfig()
        self.weight_config = weight_config or GreedyWeightConfig()

        self.rng = np.random.default_rng(self.pso_config.random_state)
        self.model_specs = self.build_model_specs()
        self.fitted_models: dict[str, object] = {}
        self.weights: ArrayF | None = None
        self.meta_model: MLPClassifier | None = None

    @staticmethod
    def build_model_specs() -> dict[str, tuple[object, SearchSpace]]:
        """Builds base models and PSO search spaces from the paper table."""
        return {
            "gb": (
                GradientBoostingClassifier(random_state=7),
                SearchSpace(bounds=((50, 200), (3, 10), (0.01, 0.1)), int_dims=(0, 1)),
            ),
            "mlp": (
                MLPClassifier(random_state=7, max_iter=200),
                SearchSpace(bounds=((50, 200), (0.0001, 0.01)), int_dims=(0,)),
            ),
            "svm": (
                SVC(probability=True, random_state=7),
                SearchSpace(bounds=((0.1, 10.0), (0.001, 0.1)), int_dims=()),
            ),
            "knn": (KNeighborsClassifier(), SearchSpace(bounds=((3, 20),), int_dims=(0,))),
            "lr": (
                LogisticRegression(max_iter=200, random_state=7),
                SearchSpace(bounds=((0.1, 10.0),), int_dims=()),
            ),
            "extra_trees": (
                ExtraTreesClassifier(random_state=7),
                SearchSpace(bounds=((50, 200), (10, 20), (2, 10)), int_dims=(0, 1, 2)),
            ),
        }

    def vector_to_params(self, model_name: str, vec: ArrayF) -> dict[str, float]:
        """Converts PSO particle vector to estimator parameter mapping."""
        if model_name == "gb":
            return {"n_estimators": int(round(vec[0])), "max_depth": int(round(vec[1])), "learning_rate": float(vec[2])}
        if model_name == "mlp":
            return {"hidden_layer_sizes": (int(round(vec[0])),), "alpha": float(vec[1])}
        if model_name == "svm":
            return {"C": float(vec[0]), "gamma": float(vec[1])}
        if model_name == "knn":
            return {"n_neighbors": int(round(vec[0]))}
        if model_name == "lr":
            return {"C": float(vec[0])}
        if model_name == "extra_trees":
            return {
                "n_estimators": int(round(vec[0])),
                "max_depth": int(round(vec[1])),
                "min_samples_split": int(round(vec[2])),
            }
        raise ValueError(f"unknown model: {model_name}")

    def clip_vector(self, vec: ArrayF, space: SearchSpace) -> ArrayF:
        """Clips particle position to parameter bounds."""
        clipped = vec.copy()
        for idx, (low, high) in enumerate(space.bounds):
            clipped[idx] = np.clip(clipped[idx], low, high)
            if idx in space.int_dims:
                clipped[idx] = round(clipped[idx])
        return clipped

    def score_model(
        self,
        estimator: object,
        x_train: ArrayF,
        y_train: ArrayF,
        x_val: ArrayF,
        y_val: ArrayF,
    ) -> float:
        """Returns fitness score for PSO (AUC on validation set)."""
        estimator.fit(x_train, y_train)
        prob = estimator.predict_proba(x_val)[:, 1]
        return float(roc_auc_score(y_val, prob))

    def run_pso(
        self,
        model_name: str,
        estimator: object,
        space: SearchSpace,
        x_train: ArrayF,
        y_train: ArrayF,
        x_val: ArrayF,
        y_val: ArrayF,
    ) -> object:
        """Runs PSO hyperparameter optimization for a single base model."""
        cfg = self.pso_config
        dims = len(space.bounds)

        positions = np.zeros((cfg.particles, dims), dtype=float)
        velocities = np.zeros((cfg.particles, dims), dtype=float)
        for p in range(cfg.particles):
            for d, (low, high) in enumerate(space.bounds):
                positions[p, d] = self.rng.uniform(low, high)
        personal_best = positions.copy()
        personal_best_score = np.full(cfg.particles, -np.inf)

        global_best = positions[0].copy()
        global_best_score = -np.inf

        for _ in range(cfg.iterations):
            for p in range(cfg.particles):
                candidate = self.clip_vector(positions[p], space)
                params = self.vector_to_params(model_name, candidate)
                model = clone(estimator).set_params(**params)
                score = self.score_model(model, x_train, y_train, x_val, y_val)

                if score > personal_best_score[p]:
                    personal_best_score[p] = score
                    personal_best[p] = candidate
                if score > global_best_score:
                    global_best_score = score
                    global_best = candidate

            for p in range(cfg.particles):
                r1 = self.rng.random(dims)
                r2 = self.rng.random(dims)
                velocities[p] = (
                    cfg.inertia * velocities[p]
                    + cfg.c1 * r1 * (personal_best[p] - positions[p])
                    + cfg.c2 * r2 * (global_best - positions[p])
                )
                velocities[p] = np.clip(velocities[p], -cfg.v_max, cfg.v_max)
                positions[p] = positions[p] + velocities[p]

        best_params = self.vector_to_params(model_name, global_best)
        return clone(estimator).set_params(**best_params)

    def brier_with_regularization(self, y_true: ArrayF, pred_matrix: ArrayF, weights: ArrayF) -> float:
        """Computes Brier + L2 objective from the paper."""
        ensemble_prob = pred_matrix @ weights
        brier = np.mean((ensemble_prob - y_true) ** 2)
        penalty = self.weight_config.l2_lambda * float(np.sum(weights**2))
        return float(brier + penalty)

    def greedy_regularized_weights(self, y_val: ArrayF, pred_matrix: ArrayF) -> ArrayF:
        """Optimizes convex weights with regularized greedy updates."""
        n_models = pred_matrix.shape[1]
        weights = np.ones(n_models, dtype=float) / n_models
        best_loss = self.brier_with_regularization(y_val, pred_matrix, weights)

        for _ in range(self.weight_config.iterations):
            improved = False
            for idx in range(n_models):
                candidate = weights.copy()
                candidate[idx] += self.weight_config.delta
                candidate = np.clip(candidate, 0.0, None)
                candidate = candidate / float(candidate.sum())

                loss = self.brier_with_regularization(y_val, pred_matrix, candidate)
                if loss < best_loss:
                    best_loss = loss
                    weights = candidate
                    improved = True
            if not improved:
                break
        return weights

    @staticmethod
    def build_meta_features(base_probs: ArrayF, weights: ArrayF) -> ArrayF:
        """Builds BlendNet inputs from unweighted and weighted predictions."""
        weighted = base_probs * weights.reshape(1, -1)
        return np.concatenate([base_probs, weighted], axis=1)

    def fit(self, x_train: ArrayF, y_train: ArrayF, x_val: ArrayF, y_val: ArrayF) -> None:
        """Fits tuned base models, greedy weights, and BlendNet meta learner."""
        y_train = np.asarray(y_train, dtype=int)
        y_val = np.asarray(y_val, dtype=int)

        base_probs_train: list[ArrayF] = []
        base_probs_val: list[ArrayF] = []

        for model_name, (base_estimator, space) in self.model_specs.items():
            tuned = self.run_pso(model_name, base_estimator, space, x_train, y_train, x_val, y_val)
            tuned.fit(x_train, y_train)
            self.fitted_models[model_name] = tuned
            base_probs_train.append(tuned.predict_proba(x_train)[:, 1])
            base_probs_val.append(tuned.predict_proba(x_val)[:, 1])

        train_mat = np.column_stack(base_probs_train)
        val_mat = np.column_stack(base_probs_val)
        self.weights = self.greedy_regularized_weights(y_val, val_mat)

        x_meta_train = self.build_meta_features(train_mat, self.weights)
        x_meta_val = self.build_meta_features(val_mat, self.weights)

        meta = MLPClassifier(
            hidden_layer_sizes=(128, 64, 32),
            activation="relu",
            solver="adam",
            max_iter=200,
            random_state=self.pso_config.random_state,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            meta.fit(x_meta_train, y_train)
            for warning in w:
                if issubclass(warning.category, ConvergenceWarning):
                    raise RuntimeError("meta-learner failed to converge; predictions unreliable") from None
        _ = meta.predict_proba(x_meta_val)[:, 1]
        self.meta_model = meta

    def check_fitted(self) -> None:
        """Validates fitted state before inference."""
        if self.meta_model is None or self.weights is None:
            raise ValueError("risk model is not fitted")

    def predict_default_probability(self, x: ArrayF) -> ArrayF:
        """Predicts default probability D_v for each row in `x`."""
        self.check_fitted()
        base_probs: list[ArrayF] = []
        for model_name in self.model_specs:
            model = self.fitted_models[model_name]
            base_probs.append(model.predict_proba(x)[:, 1])

        mat = np.column_stack(base_probs)
        x_meta = self.build_meta_features(mat, self.weights)
        return self.meta_model.predict_proba(x_meta)[:, 1]


def quote_with_estimated_default(
    engine,
    borrower: str,
    principal: float,
    term: float,
    default_probability_estimator: OptimizedGreedyWeightedRiskModel,
    feature_row: ArrayF,
    protocol_rate: float,
    max_delegation_rate: float,
):
    """Quotes a loan using an externally estimated default probability.

    Decouples the ML estimator from the core mechanism.
    """
    probabilities = default_probability_estimator.predict_default_probability(feature_row)
    default_probability = float(probabilities[0])
    return engine.quote_loan(
        borrower=borrower,
        principal=principal,
        term=term,
        default_probability=default_probability,
        protocol_rate=protocol_rate,
        max_delegation_rate=max_delegation_rate,
    )
