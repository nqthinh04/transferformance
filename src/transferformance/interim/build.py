import argparse
import sys
import time
from datetime import date
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
from loguru import logger

from transferformance.configs import PATH_INTERIM_DATA, PATH_RAW_DATA
from transferformance.interim.query import (
    InterimParams,
    build_query,
    get_default_cutoff_date,
)


class BuildError(Exception):
    pass


def _write_parquet(
    con: duckdb.DuckDBPyConnection, params: InterimParams, output_path: Path
):
    tmp_path = output_path.with_name(output_path.name + ".part")
    try:
        con.sql(build_query(params)).write_parquet(str(tmp_path))
        tmp_path.replace(output_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def build_interim(
    input_path: Path,
    output_path: Path,
    cutoff_date: date | None = None,
):
    if not input_path.is_file():
        raise BuildError(
            f"Raw database not found at {input_path}, run the download step "
            "first with `python -m transferformance.raw.download`"
        )

    with duckdb.connect(str(input_path), read_only=True) as con:
        params = InterimParams(cutoff_date=cutoff_date or get_default_cutoff_date(con))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Building {output_path} from {input_path}...")
        start = time.perf_counter()
        _write_parquet(con, params, output_path)
        elapsed = time.perf_counter() - start

    meta = pq.read_metadata(output_path)
    logger.info(
        f"Saved at {output_path.absolute()} in {elapsed:.1f}s. "
        f"No. of rows: {meta.num_rows}, no. of columns: {meta.num_columns}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the interim valuations table")
    parser.add_argument(
        "--input_path",
        type=Path,
        default=PATH_RAW_DATA,
        help="Path to the `dcaribou/transfermarkt-datasets` DuckDB file",
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

    args = parser.parse_args()

    try:
        build_interim(
            args.input_path,
            args.output_path,
            args.cutoff_date,
        )
    except (BuildError, duckdb.Error, OSError, ValueError) as err:
        logger.error(f"Build failed: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
