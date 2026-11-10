from transferformance.configs import PATH_INTERIM_DATA, PATH_RAW_DATA
from transferformance.interim.query import (
    InterimParams,
    build_query,
    get_default_cutoff_date,
)

import argparse
import sys
import time
from datetime import date
from pathlib import Path
import pyarrow.parquet as pq
import duckdb
from loguru import logger


class BuildError(Exception):
    pass


def _is_up_to_date(input_path: Path, output_path: Path) -> bool:
    if not output_path.exists():
        return False

    if output_path.stat().st_mtime < input_path.stat().st_mtime:
        logger.info(f"{output_path} is outdated compared to {input_path}, rebuilding")
        return False

    return True


def build_interim(
    input_path: Path,
    output_path: Path,
    cutoff_date: date | None = None,
    refresh: bool = False,
) -> None:
    if not input_path.is_file():
        raise BuildError(
            f"Raw database not found at {input_path}, run the download step first with `python -m transferformance.raw.download`"
        )

    if not refresh and _is_up_to_date(input_path, output_path):
        logger.info(f"{output_path} already exists, skipping build")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".part")

    start_time_in_sec = time.perf_counter()

    with duckdb.connect(input_path, read_only=True) as con:
        cutoff_date = cutoff_date or get_default_cutoff_date(
            con, InterimParams.window_in_days
        )
        params = InterimParams(cutoff_date=cutoff_date)

        logger.info(f"Building {output_path} from {input_path}...")

        try:
            con.sql(build_query(params)).write_parquet(str(tmp_path))
            tmp_path.replace(output_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    output_metadata = pq.read_metadata(output_path)
    n_rows, n_cols = output_metadata.num_rows, output_metadata.num_columns

    logger.info(
        f"Saved at {output_path.absolute()} in {time.perf_counter() - start_time_in_sec:.1f}s. No. of rows: {n_rows}, no. of columns: {n_cols}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the interim valuations table")
    parser.add_argument(
        "--input_path",
        type=Path,
        default=PATH_RAW_DATA,
        help="Path to the `dcaribou/transfermarkt-datasets`'s DuckDB database file",
    )
    parser.add_argument(
        "--output_path",
        type=Path,
        default=PATH_INTERIM_DATA,
        help="Path of the output interim `parquet` file",
    )
    parser.add_argument(
        "--cutoff_date",
        type=date.fromisoformat,
        default=None,
        help="Earliest valuation date in YYYY-MM-DD",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Build the interim `parquet` file again even if the output exists",
    )
    args = parser.parse_args()

    try:
        build_interim(
            input_path=args.input_path,
            output_path=args.output_path,
            cutoff_date=args.cutoff_date,
            refresh=args.refresh,
        )
    except (BuildError, duckdb.Error, OSError, ValueError) as err:
        logger.error(f"Build failed: {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
