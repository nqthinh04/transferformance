from dataclasses import dataclass
from datetime import date, timedelta
import duckdb


@dataclass(frozen=True)
class InterimParams:
    cutoff_date: date
    window_in_days: int = 365

    min_player_age: int = 15
    min_player_height_in_cm: int = 150
    max_appearance_minutes: int = 120


def get_default_cutoff_date(con: duckdb.DuckDBPyConnection, window_in_days: int = 365):
    (min_appearance_date,) = con.sql("""
        SELECT CAST(MIN(date) AS DATE)
        FROM appearances
    """).fetchall()[0]

    if not min_appearance_date:
        raise ValueError("The `appearances` table is empty")

    return min_appearance_date + timedelta(days=window_in_days)


def build_query(params: InterimParams) -> str:
    return f"""
        WITH valid_valuations AS (
            SELECT
                v.player_id,
                v.date::DATE AS "date",
                v.market_value_in_eur,
                p.date_of_birth::DATE AS "date_of_birth",
                p.position,
                p.height_in_cm,
                COALESCE(p.foot, 'unknown') AS "foot"
            FROM player_valuations v
                JOIN players p USING (player_id)
            WHERE
                (date >= DATE '{params.cutoff_date.isoformat()}')
                AND (v.market_value_in_eur > 0)
                AND (DATE_SUB('YEAR', p.date_of_birth::DATE, v.date::DATE) >= {params.min_player_age})
                AND (p.position <> 'Missing')
                AND (p.height_in_cm > {params.min_player_height_in_cm})
        ),
        valid_appearances AS (
            SELECT 
                player_id, 
                date::DATE AS "date", 
                minutes_played, 
                goals, 
                assists,
                yellow_cards,
                red_cards
            FROM appearances
            WHERE minutes_played BETWEEN 1 AND {params.max_appearance_minutes}
        ),
        window_{params.window_in_days}d AS (
            SELECT
                vv.player_id,
                vv.date,
                COUNT(*) AS "n_appearances",
                SUM(va.minutes_played)::INTEGER AS "minutes_per_{params.window_in_days}d",
                SUM(va.goals)::INTEGER AS "goals_per_{params.window_in_days}d",
                SUM(va.assists)::INTEGER AS "assists_per_{params.window_in_days}d",
                SUM(va.yellow_cards)::INTEGER AS "yellow_cards_per_{params.window_in_days}d",
                SUM(va.red_cards)::INTEGER AS "red_cards_per_{params.window_in_days}d"
            FROM (
                SELECT player_id, date
                FROM valid_valuations
            ) as vv
                JOIN valid_appearances AS va
                    ON (va.player_id = vv.player_id)
                    AND va.date >= vv.date - INTERVAL {params.window_in_days} DAY
                    AND va.date < vv.date
            GROUP BY vv.player_id, vv.date
        )
        SELECT *
        FROM valid_valuations vv
            JOIN window_{params.window_in_days}d AS w USING (player_id, date)
    """
