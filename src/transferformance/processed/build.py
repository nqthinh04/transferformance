from transferformance.configs import (
    PATH_INTERIM_DATA,
    PATH_PROCESSED_DATA,
    DEFAULT_WINDOW_IN_DAYS,
)

import argparse
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

TARGET = "market_value_in_eur_log1p"
PER_90_STATS = ("goals", "assists", "goals_conceded", "clean_sheets")
DAYS_IN_YEAR = 365.25
MINUTES_PER_MATCH = 90
SEASON_FIRST_MONTH = 7


class BuildError(Exception):
    pass


class FeatureError(Exception):
    pass


class FeatureStep(ABC):
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return type(self).__name__

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = [col for col in self.requires if col not in df.columns]
        if missing:
            raise FeatureError(f"{self.name} is missing columns: {missing}")

        return self._transform(df)

    @abstractmethod
    def _transform(self, df: pd.DataFrame) -> pd.DataFrame: ...


class LogTarget(FeatureStep):
    requires = ("market_value_in_eur",)
    produces = (TARGET,)

    def _transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(**{TARGET: np.log1p(df["market_value_in_eur"])})


class SeasonStart(FeatureStep):
    requires = ("date",)
    produces = ("season_start",)

    def __init__(self, first_month: int = SEASON_FIRST_MONTH):
        self.first_month = first_month

    def _transform(self, df: pd.DataFrame) -> pd.DataFrame:
        date = pd.to_datetime(df["date"])
        season_start = np.where(
            date.dt.month >= self.first_month, date.dt.year, date.dt.year - 1
        )
        return df.assign(season_start=season_start)


class Age(FeatureStep):
    requires = ("date", "date_of_birth")
    produces = ("age",)

    def _transform(self, df: pd.DataFrame) -> pd.DataFrame:
        days = pd.to_datetime(df["date"]) - pd.to_datetime(df["date_of_birth"])
        return df.assign(age=days.dt.days / DAYS_IN_YEAR)


class Per90mStats(FeatureStep):
    def __init__(self, stats: Sequence[str] = PER_90_STATS):
        self.stats = tuple(stats)
        self.requires = (
            f"minutes_per_{DEFAULT_WINDOW_IN_DAYS}d",
            *(f"{s}_per_{DEFAULT_WINDOW_IN_DAYS}d" for s in self.stats),
        )
        self.produces = tuple(f"{s}_per_90m" for s in self.stats)

    def _transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(
            **{
                f"{stat}_per_90m": df[f"{stat}_per_{DEFAULT_WINDOW_IN_DAYS}d"]
                / df[f"minutes_per_{DEFAULT_WINDOW_IN_DAYS}d"]
                * MINUTES_PER_MATCH
                for stat in self.stats
            }
        )


class AvgMinutesPerAppearance(FeatureStep):
    requires = (f"minutes_per_{DEFAULT_WINDOW_IN_DAYS}d", "n_appearances")
    produces = ("avg_minutes_per_appearance",)

    def _transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(
            avg_minutes_per_appearance=df[f"minutes_per_{DEFAULT_WINDOW_IN_DAYS}d"]
            / df["n_appearances"]
        )


class ValuationHistory(FeatureStep):
    produces = ("prev_kept_value", "days_since_prev_kept")

    def __init__(
        self,
        player_col: str = "player_id",
        date_col: str = "date",
        target: str = TARGET,
    ):
        self.player_col = player_col
        self.date_col = date_col
        self.requires = (player_col, date_col, target)
        self.target = target

    def _transform(self, df: pd.DataFrame) -> pd.DataFrame:
        date = pd.to_datetime(df[self.date_col])

        ordered = (
            df[[self.player_col, self.target]]
            .assign(_date=date)
            .sort_values([self.player_col, "_date"], kind="stable")
        )
        grouped = ordered.groupby(self.player_col, sort=False)

        prev_value = grouped[self.target].shift()
        days_since_prev_value = (ordered["_date"] - grouped["_date"].shift()).dt.days

        return df.assign(
            previous_valuation=prev_value,
            days_since_previous_valuations=days_since_prev_value,
        )


class FeaturePipeline:
    def __init__(self, steps: Sequence[FeatureStep]):
        self.steps = list(steps)

    @property
    def produced_columns(self) -> list[str]:
        return [col for step in self.steps for col in step.produces]

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        for step in self.steps:
            df = step.apply(df)
            logger.info(f"{step.name}: added {list(step.produces)}")

        return df


def build_pipeline(is_history: bool = False) -> FeaturePipeline:
    steps: list[FeatureStep] = [
        LogTarget(),
        SeasonStart(),
        Age(),
        Per90mStats(),
        AvgMinutesPerAppearance(),
    ]
    if is_history:
        steps.append(ValuationHistory())

    return FeaturePipeline(steps)


def _read_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def _write_parquet(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")

    try:
        df.to_parquet(tmp_path, index=False)
        tmp_path.replace(path)

    finally:
        tmp_path.unlink(missing_ok=True)


def build_processed(
    input_path: Path, output_path: Path, with_history: bool = False
) -> pd.DataFrame:
    logger.info(f"Read {input_path}")
    processed_df = _read_parquet(input_path)

    pipeline = build_pipeline(is_history=with_history)
    processed_df = pipeline.run(processed_df)

    _write_parquet(processed_df, output_path)

    logger.info(
        f"Saved {len(processed_df)} rows, {len(pipeline.produced_columns)} new features "
        f"at {output_path.absolute()}"
    )

    return processed_df


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the processed dataset from the interim dataset"
    )
    parser.add_argument(
        "--input", type=Path, default=PATH_INTERIM_DATA, help="Path of interim dataset"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PATH_PROCESSED_DATA,
        help="Where to save the processed dataset",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Add `previous_valuation` and `days_since_previous_valuation` features",
    )
    args = parser.parse_args()

    try:
        build_processed(args.input, args.output, with_history=args.history)
    except (FeatureError, OSError) as err:
        logger.error(f"Build failed: {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
