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
        (date >= $cutoff_date::DATE)
        AND (v.market_value_in_eur > 0)
        AND (DATE_SUB('YEAR', p.date_of_birth::DATE, v.date::DATE) >= $min_player_age::INTEGER)
        AND (p.position <> 'Missing')
        AND (p.height_in_cm > $min_player_height_in_cm::INTEGER)
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
            (cg.opponent_goals = 0) AND (a.minutes_played >= $full_match_minutes::INTEGER)
            AS INTEGER
        ) AS is_clean_sheet
    FROM appearances a
        LEFT JOIN competitions c USING (competition_id)
        LEFT JOIN club_games cg
            ON  cg.game_id = a.game_id
            AND cg.club_id = a.player_club_id
    WHERE a.minutes_played BETWEEN 1 AND $max_appearance_minutes::INTEGER
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
            AND va.date >= vv.date - INTERVAL $window_in_days DAY
            AND va.date < vv.date
),
window_amountd AS (
    SELECT
        player_id,
        date,
        COUNT(*) AS "n_appearances",
        SUM(minutes_played)::INTEGER AS "minutes_per_amountd",
        SUM(goals)::INTEGER AS "goals_per_amountd",
        SUM(assists)::INTEGER AS "assists_per_amountd",
        SUM(yellow_cards)::INTEGER AS "yellow_cards_per_amountd",
        SUM(red_cards)::INTEGER AS "red_cards_per_amountd",
        $goals_conceded AS "goals_conceded_per_amountd",
        SUM(is_clean_sheet)::INTEGER AS "clean_sheets_per_amountd",
        COALESCE(
            SUM(minutes_played) FILTER (WHERE competition_type = $league_type),
            0
        )::INTEGER AS "league_minutes_per_amountd",
        COALESCE(
            SUM(minutes_played) FILTER (WHERE competition_type IN ($cup_types)),
            0
        )::INTEGER AS "cup_minutes_per_amountd"
    FROM window_appearances
    GROUP BY player_id, date
),
main_league AS (
    SELECT player_id, date, ARG_MAX(competition_id, minutes) AS "league_id"
    FROM (
        SELECT
            player_id,
            date,
            competition_id,
            SUM(minutes_played) AS minutes
        FROM window_appearances
        WHERE competition_type = $league_type
        GROUP BY player_id, date, competition_id
    )
    GROUP BY player_id, date
)
SELECT
    vv.*,
    w.* EXCLUDE (player_id, date),
    COALESCE(ml.league_id, 'other') AS "league_id"
FROM valid_valuations vv
    JOIN window_amountd AS w USING (player_id, date)
    LEFT JOIN main_league AS ml USING (player_id, date)