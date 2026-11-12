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

    league_type: str = "domestic_league"
    cup_types: tuple[str, ...] = ("domestic_cup", "international_cup")


def get_default_cutoff_date(con: duckdb.DuckDBPyConnection, window_in_days: int = 365):
    (min_appearance_date,) = con.sql("""
        SELECT CAST(MIN(date) AS DATE)
        FROM appearances
    """).fetchall()[0]

    if not min_appearance_date:
        raise ValueError("The `appearances` table is empty")

    return min_appearance_date + timedelta(days=window_in_days)


def build_query(params: InterimParams) -> str:
    cup_types_sql = ", ".join(f"'{cup_type}'" for cup_type in params.cup_types)

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
                a.player_id,
                a.game_id,
                a.player_club_id,
                a.date::DATE AS "date",
                a.competition_id,
                COALESCE(c.type, 'unknown') AS "competition_type",
                a.minutes_played,
                a.goals,
                a.assists,
                a.yellow_cards,
                a.red_cards,
                COALESCE(cg.opponent_goals, 0) AS opponent_goals,
                CAST(
                    (cg.opponent_goals = 0) AND (a.minutes_played >= 90)
                    AS INTEGER
                ) AS is_clean_sheet
            FROM appearances a
                LEFT JOIN competitions c USING (competition_id)
                LEFT JOIN club_games cg
                    ON  cg.game_id = a.game_id
                    AND cg.club_id = a.player_club_id
            WHERE a.minutes_played BETWEEN 1 AND {params.max_appearance_minutes}
        ),
        window_appearances AS (
            SELECT
                vv.player_id,
                vv.date,
                va.competition_id,
                va.competition_type,
                va.minutes_played,
                va.goals,
                va.assists,
                va.yellow_cards,
                va.red_cards,
                va.opponent_goals,
                va.is_clean_sheet
            FROM valid_valuations AS vv
                JOIN valid_appearances AS va
                    ON (va.player_id = vv.player_id)
                    AND va.date >= vv.date - INTERVAL {params.window_in_days} DAY
                    AND va.date < vv.date
        ),
        window_{params.window_in_days}d AS (
            SELECT
                player_id,
                date,
                COUNT(*) AS "n_appearances",
                SUM(minutes_played)::INTEGER AS "minutes_per_{params.window_in_days}d",
                SUM(goals)::INTEGER AS "goals_per_{params.window_in_days}d",
                SUM(assists)::INTEGER AS "assists_per_{params.window_in_days}d",
                SUM(yellow_cards)::INTEGER AS "yellow_cards_per_{params.window_in_days}d",
                SUM(red_cards)::INTEGER AS "red_cards_per_{params.window_in_days}d",
                SUM(opponent_goals)::INTEGER AS "goals_conceded_per_{params.window_in_days}d",
                SUM(is_clean_sheet)::INTEGER AS "clean_sheets_per_{params.window_in_days}d",
                COALESCE(SUM(minutes_played) FILTER (WHERE competition_type = '{params.league_type}'), 0)::INTEGER
                    AS "league_minutes_per_{params.window_in_days}d",
                COALESCE(SUM(minutes_played) FILTER (WHERE competition_type IN ({cup_types_sql})), 0)::INTEGER
                    AS "cup_minutes_per_{params.window_in_days}d"
            FROM window_appearances
            GROUP BY player_id, date
        ),
        main_league AS (
            SELECT player_id, date, ARG_MAX(competition_id, minutes) AS "league_id"
            FROM (
                SELECT player_id, date, competition_id, SUM(minutes_played) AS minutes
                FROM window_appearances
                WHERE competition_type = '{params.league_type}'
                GROUP BY player_id, date, competition_id
            )
            GROUP BY player_id, date
        )
        SELECT
            vv.*,
            w.* EXCLUDE (player_id, date),
            COALESCE(ml.league_id, 'other') AS "league_id"
        FROM valid_valuations vv
            JOIN window_{params.window_in_days}d AS w USING (player_id, date)
            LEFT JOIN main_league AS ml USING (player_id, date)
    """