import argparse
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from loguru import logger

from transferformance.configs import PATH_PREDICTION_DATA, PATH_PROCESSED_DATA

from transferformance.model.inference import (
    COLUMN_PREV_VALUATION,
    HybridLGBModel,
    ModelError,
)

COLUMN_PLAYER_ID = "player_id"
COLUMN_DATE = "date"

DEFAULT_CUTOFF = "2024-06-30"
DEFAULT_CHUNK_SIZE = 100_000


class PredictionError(Exception):
    pass


def predict_in_chunks(
    model: HybridLGBModel, data: pd.DataFrame, chunk_size: int
) -> np.ndarray:
    """Predict EUR valuations chunk by chunk to keep memory use flat."""
    n_rows = len(data)
    values = np.empty(n_rows, dtype=float)

    for start in range(0, n_rows, chunk_size):
        stop = min(start + chunk_size, n_rows)
        chunk = data.iloc[start:stop]
        values[start:stop] = model.predict_valuation(chunk).to_numpy()
        logger.info(f"Predicted {stop:,} / {n_rows:,} rows")

    return values


def build_predictions(
    input_path: Path, output_path: Path, cutoff: str, chunk_size: int
):
    if not input_path.is_file():
        raise PredictionError(f"Processed data not found at {input_path}.")

    logger.info(f"Reading processed data from {input_path}...")
    start_time = time.perf_counter()
    data = pd.read_parquet(input_path)

    missing = [c for c in (COLUMN_PLAYER_ID, COLUMN_DATE) if c not in data.columns]
    if missing:
        raise PredictionError(f"Processed data is missing columns: {missing}")

    dates = pd.to_datetime(data[COLUMN_DATE])
    if data.duplicated([COLUMN_PLAYER_ID, COLUMN_DATE]).any():
        logger.warning(
            f"Some ({COLUMN_PLAYER_ID}, {COLUMN_DATE}) pairs appear more than once; "
            "joining these predictions to other tables will duplicate rows."
        )

    logger.info("Loading model...")
    model = HybridLGBModel.load()

    logger.info(f"Predicting {len(data):,} rows...")
    predicted_value = predict_in_chunks(model, data, chunk_size)

    previous_log = data[COLUMN_PREV_VALUATION].astype(float)
    has_history = previous_log.notna()

    predictions = pd.DataFrame(
        {
            COLUMN_PLAYER_ID: data[COLUMN_PLAYER_ID].to_numpy(),
            COLUMN_DATE: dates.to_numpy(),
            "model": np.where(has_history, "delta", "no_hist"),
            "previous_value": np.expm1(previous_log).to_numpy(),
            "predicted_value": predicted_value,
            "after_cutoff": (dates > pd.Timestamp(cutoff)).to_numpy(),
        }
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output_path, index=False)

    n_after = int(predictions["after_cutoff"].sum())
    logger.info(
        f"{has_history.mean():.0%} of rows used the delta model; "
        f"{n_after:,} rows are after {cutoff}."
    )
    logger.success(
        f"Wrote {len(predictions):,} predictions to {output_path} "
        f"in {time.perf_counter() - start_time:.1f}s."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate model predictions for the processed dataset"
    )
    parser.add_argument(
        "--input_path",
        type=Path,
        default=PATH_PROCESSED_DATA,
        help="Path to the processed `.parquet` dataset",
    )
    parser.add_argument(
        "--output_path",
        type=Path,
        default=PATH_PREDICTION_DATA,
        help="Where to write `predictions.parquet`",
    )
    parser.add_argument(
        "--cutoff",
        default=DEFAULT_CUTOFF,
        help="Last day of the training data (rows after it are flagged)",
    )
    parser.add_argument(
        "--chunk_size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Rows to predict at a time",
    )
    args = parser.parse_args()

    try:
        build_predictions(
            input_path=args.input_path,
            output_path=args.output_path,
            cutoff=args.cutoff,
            chunk_size=args.chunk_size,
        )
    except (
        PredictionError,
        ModelError,
        lgb.basic.LightGBMError,
        OSError,
        ValueError,
    ) as err:
        logger.error(f"Prediction export failed: {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
