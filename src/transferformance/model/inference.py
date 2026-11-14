import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from transferformance.configs import DIR_ROOT_MODEL

PATH_FEATURES = DIR_ROOT_MODEL / "features.json"
PATH_MODEL_LGB_DELTA = DIR_ROOT_MODEL / "lgb_delta.txt"
PATH_MODEL_LGB_NO_HIST = DIR_ROOT_MODEL / "lgb_no_hist.txt"
COLUMN_PREV_VALUATION = "previous_valuation"

EXPLANATION_META_COLUMNS = ["model", "start", "base", "prediction"]
WATERFALL_COLUMNS = ["row", "label", "measure", "log_value", "feature", "eur_value"]


class ModelError(Exception):
    pass


def load_categories(path: Path = PATH_FEATURES) -> dict[str, list]:
    return json.loads(path.read_text())["categories"]


def format_value(value) -> str:
    if pd.isna(value):
        return "missing"
    if isinstance(value, (int, float, np.number)):
        return f"{value:,.2f}"
    return str(value)


@dataclass(frozen=True)
class LGBMComponent:
    name: str
    booster: lgb.Booster
    features: list[str]
    categories: dict[str, list]

    @classmethod
    def from_file(
        cls, name: str, path: Path, all_categories: dict[str, list]
    ) -> "LGBMComponent":
        booster = lgb.Booster(model_file=str(path))
        features = booster.feature_name()

        categories = {}
        for feature in features:
            if feature in all_categories:
                categories[feature] = all_categories[feature]

        return cls(name, booster, features, categories)

    def prepare(self, data: pd.DataFrame) -> pd.DataFrame:
        frame = data[self.features].copy()
        for column, categories in self.categories.items():
            dtype = pd.CategoricalDtype(categories)
            frame[column] = frame[column].astype(dtype)
        return frame

    def predict(self, data: pd.DataFrame) -> pd.Series:
        predictions = self.booster.predict(self.prepare(data))
        return pd.Series(predictions, index=data.index)

    def contributions(self, data: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        raw = self.booster.predict(self.prepare(data), pred_contrib=True)
        values = pd.DataFrame(raw[:, :-1], index=data.index, columns=self.features)
        base = pd.Series(raw[:, -1], index=data.index)
        return values, base


class HybridLGBModel:
    def __init__(
        self,
        model_delta: LGBMComponent,
        model_no_hist: LGBMComponent,
        column_previous_valuation: str = COLUMN_PREV_VALUATION,
    ):
        self.model_delta = model_delta
        self.model_no_hist = model_no_hist
        self.column_previous_valuation = column_previous_valuation

        all_features = [*model_delta.features, *model_no_hist.features]
        self.features = list(dict.fromkeys(all_features))
        self.required = list(dict.fromkeys([*self.features, column_previous_valuation]))

    @classmethod
    def load(
        cls,
        path_delta: Path = PATH_MODEL_LGB_DELTA,
        path_no_hist: Path = PATH_MODEL_LGB_NO_HIST,
        column_previous_valuation: str = COLUMN_PREV_VALUATION,
    ) -> "HybridLGBModel":
        categories = load_categories()
        return cls(
            LGBMComponent.from_file("delta", path_delta, categories),
            LGBMComponent.from_file("no_hist", path_no_hist, categories),
            column_previous_valuation,
        )

    def predict(self, data: pd.DataFrame) -> pd.Series:
        frame = self._prepare(data)
        if frame.empty:
            return pd.Series(dtype=float, index=data.index)

        parts = []
        for component, subset in self._route(frame):
            start = self._start(component, subset)
            parts.append(start + component.predict(subset))
        return self._restore(parts, data.index)

    def predict_valuation(self, data: pd.DataFrame) -> pd.Series:
        return np.expm1(self.predict(data))

    def explain(self, data: pd.DataFrame) -> pd.DataFrame:
        frame = self._prepare(data)
        columns = ["model", "start", "base", *self.features, "prediction"]
        if frame.empty:
            return pd.DataFrame(columns=columns, index=data.index)

        parts = []
        for component, subset in self._route(frame):
            parts.append(self._explain_group(component, subset))

        explanation = self._restore(parts, data.index)
        return explanation.reindex(columns=columns)

    def waterfall(self, data: pd.DataFrame, top_k: int = 8) -> pd.DataFrame:
        explanations = self.explain(data)
        if explanations.empty:
            return pd.DataFrame(columns=WATERFALL_COLUMNS)

        frames = []
        rows = zip(explanations.iterrows(), data.iterrows())
        for (label, explanation), (_, features) in rows:
            steps = self._waterfall_steps(explanation, features, top_k)
            steps.insert(0, "row", label)
            frames.append(steps)
        return pd.concat(frames, ignore_index=True)

    def _prepare(self, data: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(data, pd.DataFrame):
            raise ModelError("Input must be a pandas `DataFrame`.")

        missing = [column for column in self.required if column not in data.columns]
        if missing:
            raise ModelError(f"Missing columns: {missing}")

        return data.reset_index(drop=True)

    def _route(self, frame: pd.DataFrame):
        has_history = frame[self.column_previous_valuation].notna()
        routes = [
            (self.model_delta, frame[has_history]),
            (self.model_no_hist, frame[~has_history]),
        ]
        for component, subset in routes:
            if not subset.empty:
                yield component, subset

    def _start(self, component: LGBMComponent, subset: pd.DataFrame) -> pd.Series:
        if component is self.model_delta:
            return subset[self.column_previous_valuation].astype(float)
        return pd.Series(0.0, index=subset.index)

    def _explain_group(
        self, component: LGBMComponent, subset: pd.DataFrame
    ) -> pd.DataFrame:
        contributions, base = component.contributions(subset)
        explanation = pd.DataFrame(
            {
                "model": component.name,
                "start": self._start(component, subset),
                "base": base,
            }
        )
        explanation = explanation.join(contributions)

        additive_columns = ["start", "base", *component.features]
        explanation["prediction"] = explanation[additive_columns].sum(axis=1)
        return explanation

    @staticmethod
    def _restore(parts: list, index: pd.Index):
        combined = pd.concat(parts).sort_index()
        combined.index = index
        return combined

    @staticmethod
    def _waterfall_steps(
        explanation: pd.Series, features: pd.Series, top_k: int
    ) -> pd.DataFrame:
        contributions = explanation.drop(EXPLANATION_META_COLUMNS).dropna()
        contributions = contributions.astype(float)

        order = contributions.abs().sort_values(ascending=False).index
        contributions = contributions[order]
        shown = contributions.iloc[:top_k]
        hidden = contributions.iloc[top_k:]

        rows = []
        if explanation["model"] == "delta":
            rows.append(("Previous value", "absolute", explanation["start"], None))
            rows.append(("Typical change", "relative", explanation["base"], None))
        else:
            rows.append(("Average value", "absolute", explanation["base"], None))

        for feature, value in shown.items():
            label = f"{feature} = {format_value(features[feature])}"
            rows.append((label, "relative", value, feature))

        if not hidden.empty:
            label = f"{len(hidden)} other features"
            rows.append((label, "relative", hidden.sum(), None))

        steps = pd.DataFrame(rows, columns=["label", "measure", "log_value", "feature"])
        cumulative = np.expm1(steps["log_value"].cumsum())
        steps["eur_value"] = cumulative.diff().fillna(cumulative.iloc[0])

        total = pd.DataFrame(
            [
                {
                    "label": "Model estimate",
                    "measure": "total",
                    "log_value": steps["log_value"].sum(),
                    "feature": None,
                    "eur_value": cumulative.iloc[-1],
                }
            ]
        )
        return pd.concat([steps, total], ignore_index=True)
