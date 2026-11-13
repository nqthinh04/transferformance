import argparse
import sys
import time
from pathlib import Path

import duckdb
from loguru import logger

from transferformance.configs import (
    PATH_RAW_DATA,
    PATH_PROCESSED_DATA,
    DIR_SRC_APP_SERVING,
)


class ServingError(Exception):
    pass


def build_serving(input_path: Path, output_dir: Path) -> None:
    if not input_path.is_file():
        raise ServingError(
            f"Raw database not found at {input_path}. "
            "Run `python -m transferformance.raw.download` first."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Exporting dashboard tables to {output_dir}...")
    start_time = time.perf_counter()

    with duckdb.connect(str(input_path), read_only=True) as con:
        logger.info("Building `players.parquet`...")

        if PATH_PROCESSED_DATA.is_file():
            model_join = f"""
            LEFT JOIN (
                SELECT DISTINCT player_id 
                FROM read_parquet('{PATH_PROCESSED_DATA}')) m 
                USING (player_id)
            """

            model_col = "(m.player_id IS NOT NULL) AS in_model"
        else:
            logger.warning(
                f"{PATH_PROCESSED_DATA} not found. Setting `in_model` to FALSE"
            )
            model_join = ""
            model_col = "FALSE AS in_model"

        con.sql(f"""
            SELECT
                p.player_id,
                p.name,
                LOWER(
                    REGEXP_REPLACE(
                        STRIP_ACCENTS(p.name), 
                        '[^a-zA-Z0-9\s]', 
                        '', 
                        'g'
                        )
                    ) AS search_name,
                p.date_of_birth,
                p.country_of_citizenship,
                p.position,
                p.sub_position,
                p.foot,
                p.height_in_cm,
                p.current_club_id,
                p.current_club_name,
                p.current_club_domestic_competition_id,
                p.contract_expiration_date,
                p.highest_market_value_in_eur,
                p.last_season,
                p.url,
                v.latest_value,
                v.latest_value_date,
                v.n_valuations,
                {model_col}
            FROM players p
            LEFT JOIN (
                SELECT 
                    player_id,
                    arg_max(market_value_in_eur, date) AS latest_value,
                    max(date) AS latest_value_date,
                    count(*) AS n_valuations
                FROM player_valuations
                GROUP BY player_id
            ) v USING (player_id)
            {model_join}
        """).write_parquet(str(output_dir / "players.parquet"))

        logger.info("Building `valuations.parquet`...")
        con.sql("""
            SELECT
                v.player_id,
                v.date,
                v.market_value_in_eur,
                a.player_club_id AS current_club_id,
                c.domestic_competition_id AS player_club_domestic_competition_id
            FROM player_valuations v
            ASOF LEFT JOIN (
                SELECT DISTINCT player_id, date, player_club_id 
                FROM appearances
            ) a
              ON v.player_id = a.player_id
             AND v.date >= a.date
            LEFT JOIN clubs c ON a.player_club_id = c.club_id
        """).write_parquet(str(output_dir / "valuations.parquet"))

        logger.info("Building `records.parquet`...")
        con.sql("""
            SELECT
                a.player_id,
                g.season,
                a.player_club_id,
                a.competition_id,
                COUNT(*) AS appearances,
                SUM(a.minutes_played) AS minutes,
                SUM(a.goals) AS goals,
                SUM(a.assists) AS assists,
                SUM(a.yellow_cards) AS yellow_cards,
                SUM(a.red_cards) AS red_cards
            FROM appearances a
            JOIN games g ON a.game_id = g.game_id
            GROUP BY 1, 2, 3, 4
        """).write_parquet(str(output_dir / "records.parquet"))

        logger.info("Building transfers.parquet...")
        con.sql("""
            SELECT
                t.player_id,
                t.transfer_date,
                fc.name AS from_club_name,
                tc.name AS to_club_name,
                t.transfer_fee,
                t.market_value_in_eur
            FROM transfers t
            LEFT JOIN clubs fc ON t.from_club_id = fc.club_id
            LEFT JOIN clubs tc ON t.to_club_id = tc.club_id
        """).write_parquet(str(output_dir / "transfers.parquet"))

        logger.info("Building clubs_and_competitions.parquet...")
        con.sql("""
            SELECT 
                competition_id AS id, 
                name, 
                COALESCE(country_name, 'World') AS country_name, 
                'competition' AS entity_type
            FROM competitions
            UNION ALL
            SELECT 
                c.club_id AS id, 
                c.name, 
                COALESCE(comp.country_name, 'World') AS country_name, 
                'club' AS entity_type
            FROM clubs c
            LEFT JOIN competitions comp ON c.domestic_competition_id = comp.competition_id
        """).write_parquet(str(output_dir / "clubs_and_competitions.parquet"))

    logger.success(
        f"Successfully built dashboard data in {time.perf_counter() - start_time:.1f}s."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export aggregated data for the Streamlit dashboard"
    )
    parser.add_argument(
        "--input_path",
        type=Path,
        default=PATH_RAW_DATA,
        help="Path to the source DuckDB database file",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=DIR_SRC_APP_SERVING,
        help="Directory where the `.parquet` files will be saved",
    )

    args = parser.parse_args()

    try:
        build_serving(
            input_path=args.input_path,
            output_dir=args.output_dir,
        )
    except (ServingError, duckdb.Error, OSError, ValueError) as err:
        logger.error(f"Serving export failed: {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
