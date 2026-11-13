from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from transferformance.configs import DEFAULT_WINDOW_IN_DAYS, DIR_SRC_INTERIM

INTERIM_QUERY_PATH = DIR_SRC_INTERIM / "interim.sql"


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

    def __post_init__(self) -> None:
        if self.window_in_days <= 0:
            raise ValueError("`window_in_days` must be positive")
        if not self.cup_types:
            raise ValueError("`cup_types` must not be empty")


def get_default_cutoff_date(
    con: duckdb.DuckDBPyConnection, window_in_days: int = DEFAULT_WINDOW_IN_DAYS
) -> date:
    (min_date,) = con.sql("SELECT CAST(MIN(date) AS DATE) FROM appearances").fetchall()[
        0
    ]

    if not min_date:
        raise ValueError("The `appearances` table is empty")
    return min_date + timedelta(days=window_in_days)


def _goals_conceded_expression(params: InterimParams) -> str:
    if params.goals_conceded_while_on_pitch:
        return f"SUM(opponent_goals * minutes_played / {params.full_match_minutes}.0)"
    return "SUM(opponent_goals)::INTEGER"


def build_query(params: InterimParams) -> str:
    if not INTERIM_QUERY_PATH.is_file():
        raise FileNotFoundError(
            f"Interim query template not found at {INTERIM_QUERY_PATH}"
        )

    template = INTERIM_QUERY_PATH.read_text()
    cup_types_sql = ", ".join(f"'{t}'" for t in params.cup_types)

    return (
        template.replace("windowd", f"{params.window_in_days}d")
        .replace("$cutoff_date", f"'{params.cutoff_date.isoformat()}'")
        .replace("$window_in_days", str(params.window_in_days))
        .replace("$min_player_age", str(params.min_player_age))
        .replace("$min_player_height_in_cm", str(params.min_player_height_in_cm))
        .replace("$max_appearance_minutes", str(params.max_appearance_minutes))
        .replace("$full_match_minutes", str(params.full_match_minutes))
        .replace("$league_type", f"'{params.league_type}'")
        .replace("$cup_types", cup_types_sql)
        .replace("$goals_conceded", _goals_conceded_expression(params))
    )
