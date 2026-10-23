TRANSFERMARTK_DB_CHECKS = {
    "errors": {
        "Missing expected tables": """
WITH expected_tables(table_name) AS (VALUES 
    ('appearances'),
    ('club_games'), 
    ('clubs'),
    ('competitions'),
    ('countries'),
    ('games'),
    ('game_events'),
    ('game_lineups'),
    ('national_teams'),
    ('player_valuations'),
    ('players'),
    ('transfers'), 
    ('version')
)
SELECT COUNT(*) AS missing_tables
FROM expected_tables et
WHERE NOT EXISTS(
    SELECT 1
    FROM information_schema.tables t
    WHERE LOWER(t.table_name) = et.table_name
)
""",
        "Missing expected columns": """
WITH expected_columns(table_name, column_name) AS (VALUES 
    ('players', 'player_id'),
    ('players', 'date_of_birth'),
    ('players', 'position'),
    ('players', 'market_value_in_eur'),
    ('players', 'highest_market_value_in_eur'),
    ('player_valuations', 'player_id'),
    ('player_valuations', 'date'),
    ('player_valuations', 'market_value_in_eur'),
    ('player_valuations', 'player_club_domestic_competition_id'),
    ('appearances', 'appearance_id'),
    ('appearances', 'game_id'),
    ('appearances', 'player_id'),
    ('appearances', 'player_club_id'),
    ('appearances', 'date'),
    ('appearances', 'minutes_played'),
    ('competitions', 'competition_id')
)
SELECT COUNT(*) AS missing_columns
FROM expected_columns ec
WHERE NOT EXISTS(
    SELECT 1
    FROM information_schema.columns c
    WHERE
        LOWER(ec.table_name) = c.table_name AND
        LOWER(ec.column_name)  = c.column_name
)
""",
        "Existing expected empty table": """
SELECT COUNT(*)
FROM (
    SELECT COUNT(*) AS cnt FROM players
    UNION ALL SELECT COUNT(*) FROM player_valuations
    UNION ALL SELECT COUNT(*) FROM appearances
    UNION ALL SELECT COUNT(*) FROM competitions
) 
WHERE cnt = 0
""",
        "Duplicate `player_id` in `players`": """
SELECT COUNT(*) AS duplicate_player_id
FROM (
    SELECT player_id
    FROM players p
    GROUP BY player_id
    HAVING COUNT(*) > 1
)
""",
        "Duplicate `game_id` in `games`": """
SELECT COUNT(*) AS duplicate_game_id
FROM (
    SELECT game_id
    FROM games
    GROUP BY game_id
    HAVING COUNT(*) > 1
)
""",
        "Duplicate `appearance_id` in `appearances`": """
SELECT COUNT(*) AS duplicate_appearance_id
FROM (
    SELECT appearance_id
    FROM appearances
    GROUP BY appearance_id
    HAVING COUNT(*) > 1
)
""",
        "Duplicate `club_id` in `clubs`": """
SELECT COUNT(*) AS duplicate_club_id
FROM (
    SELECT club_id
    FROM clubs
    GROUP BY club_id
    HAVING COUNT(*) > 1
)
""",
        "Duplicate (`player_id`, `date`) primary key in `player_valuations`": """
SELECT COUNT(*) AS duplicate_club_id
FROM (
    SELECT player_id, date
    FROM player_valuations
    GROUP BY player_id, date
    HAVING COUNT(*) > 1
)
""",
    },
    "warnings": {
        "Player missing DOB": """
SELECT COUNT(*) AS player_missing_dob
FROM players p
WHERE p.date_of_birth IS NULL
""",
        "Player missing position": """
SELECT COUNT(*) AS player_missing_position
FROM players p
WHERE p.position IS NULL
""",
        "Player's valuation being NULL or below zero": """
SELECT COUNT(*) AS invalid_valuation
FROM player_valuations v
WHERE v.market_value_in_eur IS NULL
""",
        "Minutes played of a player's appearance being below zero": """
SELECT COUNT(*) AS invalid_minutes_played
FROM appearances a
WHERE a.minutes_played < 0
""",
        "Player's valuation date being in the future": """
SELECT COUNT(*) AS future_valuation_date
FROM player_valuations v
WHERE v.date > current_date()
""",
        "Player valuation for a non-existent player": """
SELECT COUNT(*) AS orphan_player_valuation
FROM player_valuations v
LEFT JOIN players p
ON v.player_id = p.player_id
WHERE p.player_id IS NULL
""",
        "Player appearance for a non-existent player": """
SELECT COUNT(*) AS orphan_player_appearance
FROM appearances a
LEFT JOIN players p
ON a.player_id = p.player_id
WHERE p.player_id IS NULL
""",
        "Player's appearance date not matching game's date": """
SELECT count(*) AS date_mismatched
FROM appearances a
JOIN games g 
ON TRY_CAST(g.game_id AS INTEGER) = a.game_id
WHERE a.date <> g.date
""",
    },
    "infos": {
        "Latest valuation date": """
SELECT max(v.date) AS latest_valuation_date
FROM player_valuations v
""",
        "Latest game date": """
SELECT max(g.date) AS latest_game_date
FROM games g
""",
        "Valuation per player (min, median, max)": """
SELECT 
    MIN(n)    AS min_valuations,
    MEDIAN(n) AS median_valuations,
    MAX(n)    AS max_valuations
FROM (
    SELECT player_id, COUNT(*) AS n
    FROM player_valuations
    GROUP BY player_id
)
""",
        "Players with a valuation but with zero appearance": """
SELECT COUNT(*) AS players_without_appearances
FROM (
    SELECT DISTINCT player_id 
    FROM player_valuations
) v
LEFT JOIN (
    SELECT DISTINCT player_id 
    FROM appearances
) a
ON a.player_id = v.player_id
WHERE a.player_id IS NULL
""",
    },
}
