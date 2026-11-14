import argparse
import sys
from pathlib import Path

import pandas as pd
from loguru import logger

from transferformance.configs import PATH_PROCESSED_DATA, DIR_PROCESSED_SPLITS

VAL_START = pd.Timestamp("2024-07-01")
TEST_START = pd.Timestamp("2025-07-01")


class SplitError(Exception):
    pass


def build_splits(input_path: Path, output_dir: Path):
    if not input_path.is_file():
        raise SplitError(
            f"Features not found at {input_path}, run the features step first"
        )

    df = pd.read_parquet(input_path)
    dates = pd.to_datetime(df["date"])

    splits = {
        "train": df[dates < VAL_START],
        "val": df[(dates >= VAL_START) & (dates < TEST_START)],
        "test": df[dates >= TEST_START],
    }

    empty = [name for name, part in splits.items() if part.empty]
    if empty:
        raise SplitError(f"Empty split(s): {empty}")

    output_dir.mkdir(parents=True, exist_ok=True)


    logger.info(f"Creating splits from {input_path} to {output_dir}")
    for split_name, split in splits.items():
        split_output_path = output_dir / f"{split_name}.parquet"
        split.to_parquet(split_output_path, index=False)
        logger.info(f"`{split_name}` created. Shape: {split.shape}. Path: {split_output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split the processed datasets into training, validation, and test sets by date"
    )
    parser.add_argument("--input_path", type=Path, default=PATH_PROCESSED_DATA, help="Path to the processed dataset")
    parser.add_argument("--output_dir", type=Path, default=DIR_PROCESSED_SPLITS, help="Directory to the processed dataset's splits")
    args = parser.parse_args()

    try:
        build_splits(args.input_path, args.output_dir)
    except (SplitError, OSError) as err:
        logger.error(f"Split failed: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
