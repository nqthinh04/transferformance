from transferformance.configs import DEFAULT_WINDOW_IN_DAYS

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb


@dataclass(frozen=True)
class InterimParams:
    cutoff_date: date
    window_in_days: int = DEFAULT_WINDOW_IN_DAYS

    min_player_age: int = 15
    min_player_height_in_cm: int = 150
    max_appearance_minutes: int = 120
    full_match_minutes: int = 90

    league_type: str = "domestic_league"
    cup_types: tuple[str, ...] = ("domestic_cup", "international_cup")

    goals_conceded_while_on_pitch: bool = False

    def __post_init__(self):
        if self.window_in_days <= 0:
            raise ValueError("`window_in_days` must be positive")
        if not self.cup_types:
            raise ValueError("`cup_types` must not be empty")


_FINAL_SELECT = """
    SELECT
        vv.*,
        w.* EXCLUDE (player_id, date),
        COALESCE(ml.league_id, 'other') AS league_id
    FROM valid_valuations vv
        JOIN window_features w USING (player_id, date)
        LEFT JOIN main_league ml USING (player_id, date)
"""


def get_default_cutoff_date(
    con: duckdb.DuckDBPyConnection, window_in_days: int = DEFAULT_WINDOW_IN_DAYS
) -> date:
    (min_date,) = con.sql("SELECT CAST(MIN(date) AS DATE) FROM appearances").fetchall()[
        0
    ]

    if not min_date:
        raise ValueError("The `appearances` table is empty")
    return min_date + timedelta(days=window_in_days)


def _minutes_where(condition: str) -> str:
    return f"COALESCE(SUM(minutes_played) FILTER (WHERE {condition}), 0)::INTEGER"


def _window_features(params: InterimParams) -> dict[str, str]:
    window_in_days_str = f"{params.window_in_days}d"

    if params.goals_conceded_while_on_pitch:
        goals_conceded = (
            f"SUM(opponent_goals * minutes_played / {params.full_match_minutes}.0)"
        )
    else:
        goals_conceded = "SUM(opponent_goals)::INTEGER"

    return {
        "n_appearances": "COUNT(*)",
        f"minutes_per_{window_in_days_str}": "SUM(minutes_played)::INTEGER",
        f"goals_per_{window_in_days_str}": "SUM(goals)::INTEGER",
        f"assists_per_{window_in_days_str}": "SUM(assists)::INTEGER",
        f"yellow_cards_per_{window_in_days_str}": "SUM(yellow_cards)::INTEGER",
        f"red_cards_per_{window_in_days_str}": "SUM(red_cards)::INTEGER",
        f"goals_conceded_per_{window_in_days_str}": goals_conceded,
        f"clean_sheets_per_{window_in_days_str}": "SUM(is_clean_sheet)::INTEGER",
        f"league_minutes_per_{window_in_days_str}": _minutes_where(
            f"competition_type = '{params.league_type}'"
        ),
        f"cup_minutes_per_{window_in_days_str}": _minutes_where(
            f"""competition_type IN ({", ".join(f"'{t}'" for t in params.cup_types)})"""
        ),
    }


def _valid_valuations(params: InterimParams) -> str:
    return f"""
        SELECT
            v.player_id,
            v.date::DATE AS date,
            v.market_value_in_eur,
            p.date_of_birth::DATE AS date_of_birth,
            p.position,
            p.height_in_cm,
            COALESCE(p.foot, 'unknown') AS foot
        FROM player_valuations v
            JOIN players p USING (player_id)
        WHERE v.date::DATE >= DATE '{params.cutoff_date.isoformat()}'
          AND v.market_value_in_eur > 0
          AND DATE_SUB('YEAR', p.date_of_birth::DATE, v.date::DATE) >= {params.min_player_age}
          AND p.position <> 'Missing'
          AND p.height_in_cm > {params.min_player_height_in_cm}
    """


def _valid_appearances(params: InterimParams) -> str:
    return f"""
        SELECT
            a.player_id,
            a.date::DATE AS match_date,
            a.competition_id,
            COALESCE(c.type, 'unknown') AS competition_type,
            a.minutes_played,
            a.goals,
            a.assists,
            a.yellow_cards,
            a.red_cards,
            cg.opponent_goals,
            (cg.opponent_goals = 0
                AND a.minutes_played >= {params.full_match_minutes})::INTEGER AS is_clean_sheet
        FROM appearances a
            LEFT JOIN competitions c USING (competition_id)
            JOIN club_games cg
              ON cg.game_id = a.game_id AND cg.club_id = a.player_club_id
        WHERE a.minutes_played BETWEEN 1 AND {params.max_appearance_minutes}
    """


def _window_appearances(params: InterimParams) -> str:
    return f"""
        SELECT vv.player_id, vv.date, va.* EXCLUDE (player_id, match_date)
        FROM valid_valuations vv
            JOIN valid_appearances va
              ON va.player_id = vv.player_id
             AND va.match_date >= vv.date - INTERVAL {params.window_in_days} DAY
             AND va.match_date <  vv.date
    """


def _window_features_cte(params: InterimParams) -> str:
    aggs = ",\n".join(
        f'{expr} AS "{name}"' for name, expr in _window_features(params).items()
    )
    return f"""
        SELECT player_id, date, {aggs}
        FROM window_appearances
        GROUP BY player_id, date
    """


def _main_league(params: InterimParams) -> str:
    return f"""
        SELECT player_id, date, competition_id AS league_id
        FROM window_appearances
        WHERE competition_type = '{params.league_type}'
        GROUP BY player_id, date, competition_id
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_id, date
            ORDER BY SUM(minutes_played) DESC, competition_id
        ) = 1
    """


def build_query(params: InterimParams) -> str:
    ctes = {
        "valid_valuations": _valid_valuations(params),
        "valid_appearances": _valid_appearances(params),
        "window_appearances": _window_appearances(params),
        "window_features": _window_features_cte(params),
        "main_league": _main_league(params),
    }

    sql_ctes = ",\n".join(f"{name} AS ({body})" for name, body in ctes.items())

    return f"WITH {sql_ctes}\n{_FINAL_SELECT}"
