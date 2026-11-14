import math
import re
import unicodedata

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from rapidfuzz import fuzz, process

from transferformance.configs import DIR_SRC_APP_SERVING
from transferformance.model.inference import HybridLGBModel

st.set_page_config(page_title="Transferformance", layout="wide")

ORANGE = "#f59e0b"
PALLETE = ["#00E5FF", "#FF2A6D", "#05FFA1", "#FFB703", "#7209B7"]

NA = "N/A"

MODEL_TRAIN_CUTOFF = "2024-07-01"

PLOT_HEIGHT, BOX_HEIGHT = 420, 580
SLIDER_VALUATION_STEP = 1_000_000
STATS = ["appearances", "minutes", "goals", "assists", "yellow_cards", "red_cards"]
MONEY_COLUMNS = ["transfer_fee", "market_value_in_eur"]

COMPETITION_OVERRIDES = {
    "KLUB": "Club World Cup",
    "CGB": "Carabao Cup",
    "POCP": "Taca de Portugal",
}
COMPETITION_CONFENDERATION_ACRONYMS = {
    "fa",
    "efl",
    "dfb",
    "fifa",
    "uefa",
    "afc",
    "caf",
    "concacaf",
    "conmebol",
}

NAME_FILTERS = {
    "Position": "position",
    "Citizenship": "country_of_citizenship",
    "Club": "current_club_name",
}

st.markdown(
    """
    <style>
    [data-testid="stMetric"], div[data-testid="stContainer"] {
        padding: 4px !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.2rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)


@st.cache_data
def read_serving_parquet(name, player_id=None, columns=None) -> pd.DataFrame:
    df = pd.read_parquet(
        DIR_SRC_APP_SERVING / f"{name}.parquet",
        columns=columns,
        filters=None if player_id is None else [("player_id", "==", player_id)],
    )

    for col in df.filter(regex="date$"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_resource
def get_model() -> HybridLGBModel:
    return HybridLGBModel.load()


@st.cache_data
def get_features(player_id: int) -> pd.DataFrame:
    cols = ["player_id", "date", "market_value_in_eur", *get_model().required]
    df = read_serving_parquet("processed", player_id, list(dict.fromkeys(cols)))

    return (
        df.loc[df["date"] >= MODEL_TRAIN_CUTOFF]
        .sort_values("date")
        .reset_index(drop=True)
    )


def get_records(player_id: int, country) -> pd.DataFrame:
    clubs = read_serving_parquet("clubs_and_competitions")
    names = dict(zip(clubs["id"].astype("string"), clubs["name"]))
    record = read_serving_parquet("records", player_id)

    record["club"] = (
        record["player_club_id"]
        .astype("string")
        .map(names)
        .fillna(country or "National Team")
    )

    competition = record["competition_id"].astype("string")

    record["competition"] = (
        competition.map(COMPETITION_OVERRIDES)
        .fillna(competition.map(names).map(format_competition_name, na_action="ignore"))
        .fillna(competition)
    )
    return record


# FORMATTERS AND GETTERS
def format_value(value, template="{}") -> str:
    return NA if pd.isna(value) else template.format(value)


def format_date(value) -> str:
    date = pd.to_datetime(value, errors="coerce")
    return NA if pd.isna(date) else f"{date:%Y-%m-%d}"


def format_money(value) -> str:
    if pd.isna(value):
        return NA

    sgn = "-" if value < 0 else ""
    value = abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if value >= limit:
            return f"{sgn}€{value / limit:.1f}".removesuffix(".0") + suffix
    return f"{sgn}€{value:,.0f}"


def format_competition_name(name: str) -> str:
    words = name.replace("-", " ").split()
    return " ".join(
        w.upper() if w.lower() in COMPETITION_CONFENDERATION_ACRONYMS else w.title()
        for w in words
    )


def get_player_age(player: pd.Series):
    dob = pd.to_datetime(player["date_of_birth"], errors="coerce")
    return None if pd.isna(dob) else (pd.Timestamp.today() - dob).days // 365


def get_feature_label(name: str, value) -> str:
    if pd.isna(value):
        text = NA
    elif name == "previous_valuation":
        text = format_money(math.expm1(value))
    elif isinstance(value, str):
        text = value
    elif abs(value) >= 100:
        text = f"{value:,.0f}"
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{name} ▶ {text}"


def get_label_steps(steps: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    steps["label"] = [
        get_feature_label(feature, row[feature]) if isinstance(feature, str) else text
        for text, feature in zip(steps["label"], steps["feature"])
    ]
    return steps


def get_metrics(items: list[tuple]):
    for col, (label, value, *help_text) in zip(st.columns(len(items)), items):
        col.metric(label, value, help=(help_text or [None])[0], border=True)


def value_figure(
    valuations: pd.DataFrame, model_predictions: pd.DataFrame | None
) -> go.Figure:
    fig = px.line(
        valuations,
        x="date",
        y="market_value_in_eur",
        markers=True,
        labels={"date": "", "market_value_in_eur": "Market value (€)"},
    )
    fig.update_traces(
        name="Transfermarkt",
        showlegend=True,
        hovertemplate="%{x|%d %b %Y}<br>Transfermarkt: €%{y:,.0f}<extra></extra>",
    )

    if model_predictions is not None:
        before = valuations[valuations["date"] < MODEL_TRAIN_CUTOFF]

        sizes = [6] * len(model_predictions)
        if not before.empty:
            anchor = before.tail(1)[["date", "market_value_in_eur"]]
            anchor = anchor.assign(model_value=anchor["market_value_in_eur"])
            model_predictions = pd.concat(
                [anchor, model_predictions], ignore_index=True
            )
            sizes = [0, *sizes]

        fig.add_trace(
            go.Scatter(
                x=model_predictions["date"],
                y=model_predictions["market_value_in_eur"],
                mode="lines",
                line={"width": 0},
                hoverinfo="skip",
                showlegend=False,
            )
        )

        fig.add_trace(
            go.Scatter(
                x=model_predictions["date"],
                y=model_predictions["model_value"],
                mode="lines+markers",
                name="Model estimate",
                line={"color": ORANGE, "dash": "dot"},
                marker={"size": sizes},
                fill="tonexty",
                fillcolor="rgba(245, 158, 11, 0.2)",
                hovertemplate="%{x|%d %b %Y}<br>Model: €%{y:,.0f}<extra></extra>",
            )
        )

        fig.add_shape(
            type="line",
            x0=MODEL_TRAIN_CUTOFF,
            x1=MODEL_TRAIN_CUTOFF,
            y0=0,
            y1=1,
            yref="paper",
            line={"dash": "dash", "width": 1, "color": "gray"},
        )
        fig.add_annotation(
            x=MODEL_TRAIN_CUTOFF,
            y=1,
            yref="paper",
            text="Model cut-off",
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
        )

    fig.update_yaxes(tickprefix="€", tickformat=",.0f", rangemode="tozero")
    fig.update_layout(legend={"orientation": "h", "y": 1.15}, height=PLOT_HEIGHT)
    return fig


def get_waterfall_figure(steps: pd.DataFrame) -> go.Figure:
    text = [
        format_money(abs(v)) if m == "absolute" else format_money(v)
        for m, v in zip(steps["measure"], steps["eur_value"])
    ]
    fig = go.Figure(
        go.Waterfall(
            orientation="h",
            measure=steps["measure"],
            y=steps["label"],
            x=steps["eur_value"],
            text=text,
            textposition="outside",
            cliponaxis=False,
            increasing={"marker": {"color": PALLETE[0]}},
            decreasing={"marker": {"color": PALLETE[1]}},
            totals={"marker": {"color": ORANGE}},
            connector={"line": {"width": 1, "color": "gray"}},
            hovertemplate="%{y}<br>%{text}<extra></extra>",
        )
    )
    fig.update_xaxes(tickprefix="€", tickformat="~s")
    fig.update_yaxes(autorange="reversed", automargin=True)
    fig.update_layout(
        height=PLOT_HEIGHT, showlegend=False, margin={"l": 0, "r": 30, "t": 10, "b": 0}
    )
    return fig


def page_overview():
    players = read_serving_parquet("players")
    records = read_serving_parquet("records")
    valuations = read_serving_parquet("valuations")
    predictions = read_serving_parquet("predictions")

    st.title("Overview")

    # Metrics
    top_players = (
        players.dropna(subset=["latest_value", "name"])
        .nlargest(10, "latest_value")
        .sort_values("latest_value")
    )
    best = top_players.iloc[-1]
    get_metrics(
        [
            ("Total Players", f"{len(players):,}"),
            ("Total Leagues", f"{records['competition_id'].nunique():,}"),
            ("Total Seasons", f"{records['season'].nunique():,}"),
            (f"Highest Value ▶ {best['name']}", f"€{best['latest_value']:,.0f}"),
        ]
    )

    col1, col2 = st.columns(2)

    # Top 10 most valuable players
    with col1:
        st.subheader("Top 10 Most Valuable Players")
        fig_top = px.bar(
            top_players,
            x="latest_value",
            y="name",
            orientation="h",
            labels={"latest_value": "Market Value (€)", "name": ""},
        )
        fig_top.update_traces(hovertemplate="<b>%{y}</b><br>€%{x:,.0f}<extra></extra>")
        fig_top.update_xaxes(tickprefix="€", tickformat=",.0f")
        st.plotly_chart(fig_top, width="stretch")

    # Market value distribution
    with col2:
        st.subheader("Market Value Distribution")
        val_dist_df = valuations.merge(
            players[["player_id", "position"]], on="player_id", how="left"
        ).sort_values("position")

        fig_dist = px.histogram(
            val_dist_df,
            x="market_value_in_eur",
            color="position",
            nbins=100,
            labels={"market_value_in_eur": "Market Value (€)"},
            log_y=True,
            color_discrete_sequence=PALLETE,
        )
        fig_dist.update_xaxes(tickprefix="€", tickformat=",.0f")
        fig_dist.update_yaxes(title="No. of valuations", type="log")
        fig_dist.update_traces(
            hovertemplate="€%{x:,.0f}<br>%{y:,} players<extra></extra>"
        )
        st.plotly_chart(fig_dist, width="stretch")

    # Actual vs Predicted scatter
    valuations = valuations.assign(
        date=pd.to_datetime(valuations["date"], errors="coerce")
    )
    predictions = predictions.assign(
        date=pd.to_datetime(predictions["date"], errors="coerce")
    )

    scatter_df = (
        predictions.merge(valuations, on=["player_id", "date"], how="inner")
        .merge(players[["player_id", "name", "position"]], on="player_id", how="left")
        .dropna(subset=["market_value_in_eur", "predicted_value"])
        .sort_values("market_value_in_eur", ascending=False)
        .head(1000)
        .sort_values("position")
        .reset_index(drop=True)
    )

    st.subheader("Actual vs Predicted Market Value (Top 1,000 Valuations)")

    fig_scatter = px.scatter(
        scatter_df,
        x="market_value_in_eur",
        y="predicted_value",
        color="position",
        hover_name="name",
        labels={
            "market_value_in_eur": "Actual Market Value (€)",
            "predicted_value": "Predicted Value (€)",
        },
        opacity=0.7,
        color_discrete_sequence=PALLETE,
        hover_data={
            "date": True,
            "position": True,
            "market_value_in_eur": ":,.0f",
            "predicted_value": ":,.0f",
        },
    )
    fig_scatter.update_traces(
        hovertemplate=(
            "<b>%{hovertext}</b>"
            "<br>Date: %{customdata[0]|%d %b %Y}"
            "<br>Position: %{customdata[1]}"
            "<br>Actual: €%{x:,.0f}"
            "<br>Predicted: €%{y:,.0f}<extra></extra>"
        )
    )

    min_val = min(
        scatter_df["market_value_in_eur"].min(), scatter_df["predicted_value"].min()
    )
    max_val = max(
        scatter_df["market_value_in_eur"].max(), scatter_df["predicted_value"].max()
    )
    fig_scatter.add_shape(
        type="line",
        x0=min_val,
        y0=min_val,
        x1=max_val,
        y1=max_val,
        line=dict(color=ORANGE, dash="dash", width=2),
    )
    fig_scatter.update_xaxes(tickprefix="€", tickformat=",.0f")
    fig_scatter.update_yaxes(tickprefix="€", tickformat=",.0f")
    st.plotly_chart(fig_scatter, width="stretch")

    # Top 10 clubs by actual vs predicted valuation
    club_df = (
        predictions.merge(valuations, on=["player_id", "date"], how="inner")
        .merge(
            players[["player_id", "name", "position", "current_club_name"]],
            on="player_id",
            how="left",
        )
        .assign(
            market_value_in_eur=lambda d: pd.to_numeric(
                d["market_value_in_eur"], errors="coerce"
            ),
            predicted_value=lambda d: pd.to_numeric(
                d["predicted_value"], errors="coerce"
            ),
        )
        .dropna(subset=["market_value_in_eur", "predicted_value", "current_club_name"])
    )

    latest_per_player = club_df.sort_values("date").groupby("player_id").tail(1)

    top_clubs = (
        latest_per_player.groupby("current_club_name")
        .agg(
            Actual=("market_value_in_eur", "sum"),
            Predicted=("predicted_value", "sum"),
            player_count=("player_id", "count"),
        )
        .reset_index()
        .nlargest(10, "Actual")
    )

    melted_clubs = top_clubs.melt(
        id_vars=["current_club_name"],
        value_vars=["Actual", "Predicted"],
        var_name="Valuation Type",
        value_name="Value",
    )

    st.subheader("Actual vs Predicted Valuation (Top 10 Clubs)")

    fig_clubs = px.bar(
        melted_clubs,
        x="Value",
        y="current_club_name",
        color="Valuation Type",
        barmode="group",
        orientation="h",
        labels={
            "Value": "Squad Value (€)",
            "current_club_name": "",
            "Valuation Type": "",
        },
        color_discrete_sequence=[ORANGE, PALLETE[0]],
    )
    fig_clubs.update_layout(yaxis={"categoryorder": "total ascending"})
    fig_clubs.update_traces(
        hovertemplate="<b>%{y}</b><br>%{fullData.name}: €%{x:,.0f}<extra></extra>"
    )
    fig_clubs.update_xaxes(tickprefix="€", tickformat=",.0f")
    st.plotly_chart(fig_clubs, width="stretch")

    # League distribution of market values
    comp_df = (
        predictions.merge(valuations, on=["player_id", "date"], how="inner")
        .merge(players[["player_id", "name"]], on="player_id", how="left")
        .assign(
            market_value_in_eur=lambda d: pd.to_numeric(
                d["market_value_in_eur"], errors="coerce"
            )
        )
        .dropna(subset=["market_value_in_eur", "player_club_domestic_competition_id"])
    )

    if comp_df.empty:
        st.warning("No valuation data available for competitions.")
        return

    latest_comp = (
        comp_df.sort_values("date")
        .groupby("player_id")
        .tail(1)
        .query("player_club_domestic_competition_id != 'JAP1'")
    )

    competition_order = (
        latest_comp.groupby("player_club_domestic_competition_id")[
            "market_value_in_eur"
        ]
        .median()
        .sort_values(ascending=False)
        .index.tolist()
    )

    latest_comp = latest_comp.assign(
        player_club_domestic_competition_id=pd.Categorical(
            latest_comp["player_club_domestic_competition_id"],
            categories=competition_order,
            ordered=True,
        )
    ).sort_values("player_club_domestic_competition_id")

    st.subheader("Market Value Distribution by Competition")

    fig_comp = px.box(
        latest_comp,
        x="player_club_domestic_competition_id",
        y="market_value_in_eur",
        color="player_club_domestic_competition_id",
        labels={
            "player_club_domestic_competition_id": "Competition",
            "market_value_in_eur": "Market Value (€)",
        },
        color_discrete_sequence=PALLETE,
    )
    fig_comp.update_layout(showlegend=False)
    fig_comp.update_yaxes(
        type="log",
        tickprefix="€",
        tickvals=[
            10000,
            20000,
            50000,
            100000,
            200000,
            500000,
            1000000,
            2000000,
            5000000,
            10000000,
            20000000,
            50000000,
            100000000,
            200000000,
        ],
        ticktext=[
            "€10k",
            "€20k",
            "€50k",
            "€100k",
            "€200k",
            "€500k",
            "€1M",
            "€2M",
            "€5M",
            "€10M",
            "€20M",
            "€50M",
            "€100M",
            "€200M",
        ],
    )
    fig_comp.update_traces(
        hovertemplate="<b>%{x}</b><br>Value: €%{y:,.0f}<extra></extra>"
    )
    st.plotly_chart(fig_comp, width="stretch")


def clean_names(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def find_fuzzy(players: pd.DataFrame, query: str, limit: int = 10) -> pd.DataFrame:
    hits = process.extract(
        query,
        players["search_name"].fillna(""),
        scorer=fuzz.WRatio,
        score_cutoff=75,
        limit=50,
    )
    if not hits:
        return players.iloc[:0]

    scores = pd.Series({key: score for _, score, key in hits})
    found = players.loc[scores.index].assign(band=scores // 10)
    return found.sort_values(["band", "latest_value"], ascending=False).head(limit)


def page_search():
    players = read_serving_parquet("players")
    st.title("Player Search")
    query = clean_names(
        st.text_input("Search by name", placeholder="e.g. Haaland, Bellingham")
    )

    top = (
        math.ceil(players["latest_value"].max() / SLIDER_VALUATION_STEP)
        * SLIDER_VALUATION_STEP
    )
    low, high = st.slider(
        "Market value range (€)", 0, top, (0, top), step=SLIDER_VALUATION_STEP
    )
    df = players
    if (low, high) != (0, top):
        df = df[df["latest_value"].between(low, high)]
    for col, (label, field) in zip(st.columns(len(NAME_FILTERS)), NAME_FILTERS.items()):
        picked = col.multiselect(label, sorted(players[field].dropna().unique()))
        if picked:
            df = df[df[field].isin(picked)]

    results = find_fuzzy(df, query) if query else df.nlargest(50, "latest_value")
    if results.empty:
        st.warning("No players found.")
        return

    st.caption(
        f"{len(df):,} players match the filters (showing {len(results)}). "
        "Tick the box next to a player to open their page."
    )
    event = st.dataframe(
        results[
            [
                "name",
                "current_club_name",
                "position",
                "country_of_citizenship",
                "latest_value",
            ]
        ],
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="player_results",
        column_config={
            "name": "Player",
            "current_club_name": "Club",
            "position": "Position",
            "country_of_citizenship": "Citizenship",
            "latest_value": st.column_config.NumberColumn(
                "Value (€)", format="localized"
            ),
        },
    )
    if rows := event.selection.rows:
        st.session_state["player_id"] = int(results.iloc[rows[0]]["player_id"])
        st.switch_page(PLAYER)


def page_player():
    players = read_serving_parquet("players")
    raw = st.session_state.get("player_id") or st.query_params.get("player") or ""
    match = players[players["player_id"] == pd.to_numeric(raw, errors="coerce")]
    if match.empty:
        st.title("Player")
        st.info("No player selected. Pick one from Player Search.")
        st.page_link(SEARCH, label="Go to Player Search", icon="🔎")
        return

    p = match.iloc[0]
    player_id = int(p["player_id"])
    st.query_params["player"] = str(player_id)
    rec = get_records(player_id, p["country_of_citizenship"])

    st.page_link(SEARCH, label="Back to search", icon="◀")

    with st.container(border=True):
        title, link = st.columns([5, 1], vertical_alignment="center")
        title.title(p["name"])
        if pd.notna(p["url"]):
            link.link_button(
                "Transfermarkt ↗", p["url"], type="primary", width="stretch"
            )
    get_metrics(
        [
            ("Current club", format_value(p["current_club_name"])),
            ("Citizenship", format_value(p["country_of_citizenship"])),
            ("Sub-position", format_value(p["sub_position"])),
            ("Foot", format_value(p["foot"]).title()),
            ("Height", format_value(p["height_in_cm"], "{:.0f} cm")),
            ("Contract until", format_date(p["contract_expiration_date"])),
        ]
    )

    if rec.empty:
        recent = [("Minutes", NA), ("Goals + assists", NA)]
    else:
        season = rec["season"].max()
        s = (
            rec.loc[rec["season"] == season, ["minutes", "goals", "assists"]]
            .sum()
            .astype(int)
        )
        recent = [
            (f"Minutes ▶ {season}", f"{s['minutes']:,}"),
            (f"Goals + Assists ▶ {season}", f"{s['goals']} + {s['assists']}"),
        ]
    get_metrics(
        [
            (
                "Current value",
                format_money(p["latest_value"]),
                format_value(p["latest_value"], "€{:,.0f}"),
            ),
            (
                "Peak value",
                format_money(p["highest_market_value_in_eur"]),
                format_value(p["highest_market_value_in_eur"], "€{:,.0f}"),
            ),
            ("Born", format_date(p["date_of_birth"])),
            ("Age", format_value(get_player_age(p))),
            *recent,
        ]
    )

    in_model = pd.notna(p["in_model"]) and bool(p["in_model"])
    if in_model:
        st.warning(
            "**Note:** The model does not account for external factors like injuries, "
            "suspensions, or off-field factors; nor does it use advanced metrics like XG.",
            icon="⚠️",
        )

    features = get_features(player_id) if in_model else pd.DataFrame()
    note = None

    if features.empty:
        note = (
            f"No valuations since {MODEL_TRAIN_CUTOFF}"
            if in_model
            else "Not covered by the model"
        )

    valuations = read_serving_parquet("valuations", player_id).sort_values("date")

    container_left, container_right = st.columns(2)
    with container_left.container(border=True, height=BOX_HEIGHT):
        st.subheader("Market value history")

        if valuations.empty:
            st.badge("No valuations recorded", color="gray")
        else:
            preds = None
            if not note:
                preds = features.assign(
                    model_value=get_model().predict_valuation(features)
                )
                preds = preds[["date", "market_value_in_eur", "model_value"]]
            st.plotly_chart(value_figure(valuations, preds), width="stretch")
            if note:
                st.badge(note, color="gray")

    with container_right.container(border=True, height=BOX_HEIGHT):
        st.subheader("What drives the model prediction?")
        if note:
            st.badge(note, color="gray")
        else:
            latest = features.tail(1)
            steps = get_label_steps(get_model().waterfall(latest), latest.iloc[0])
            st.caption(f"Latest estimate ▶ {latest['date'].iloc[0]:%d %b %Y}")
            st.plotly_chart(get_waterfall_figure(steps), width="stretch")

    with st.container(border=True):
        st.subheader("Career statistics")
        if rec.empty:
            st.caption("No appearance records for this player.")
        else:
            t = rec[STATS].sum().astype(int)
            get_metrics(
                [
                    ("Appearances", f"{t['appearances']:,}"),
                    ("Minutes", f"{t['minutes']:,}"),
                    ("Goals", f"{t['goals']:,}"),
                    ("Assists", f"{t['assists']:,}"),
                    ("Cards", f"{t['yellow_cards']} 🟡 {t['red_cards']} 🔴"),
                ]
            )
            fig = px.bar(
                rec.groupby("season")[["goals", "assists"]].sum(),
                barmode="group",
                labels={"value": "", "season": "", "variable": ""},
            )
            fig.update_xaxes(type="category")
            fig.update_layout(legend={"orientation": "h", "y": 1.1})

            chart, table = st.columns([1, 2])
            chart.plotly_chart(fig, width="stretch")
            table.dataframe(
                rec.sort_values("season", ascending=False)[
                    ["season", "club", "competition", *STATS]
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "season": "Season",
                    "club": "Club",
                    "competition": "Competition",
                    "appearances": "Apps",
                    "minutes": st.column_config.NumberColumn(
                        "Minutes", format="localized"
                    ),
                    "goals": "Goals",
                    "assists": "Assists",
                    "yellow_cards": "🟡",
                    "red_cards": "🔴",
                },
            )

    transfers = read_serving_parquet("transfers", player_id)

    predictions_configs = {}
    if in_model:
        predictions = read_serving_parquet(
            "predictions", player_id, columns=["date", "predicted_value"]
        )
        predictions_configs = {
            "predicted_value": st.column_config.NumberColumn(
                "Predicted value (€)", format="localized"
            )
        }

        transfers["transfer_date"] = pd.to_datetime(
            transfers["transfer_date"], errors="coerce"
        ).astype("datetime64[ns]")
        predictions["date"] = pd.to_datetime(
            predictions["date"], errors="coerce"
        ).astype("datetime64[ns]")

        transfers = pd.merge_asof(
            transfers.sort_values("transfer_date"),
            predictions.sort_values("date").rename(columns={"date": "transfer_date"}),
            on="transfer_date",
            direction="backward",
        )

        transfers["predicted_value"] = (
            transfers["predicted_value"].round().astype("Int64")
        )

    transfers[MONEY_COLUMNS] = transfers[MONEY_COLUMNS].apply(
        pd.to_numeric, errors="coerce"
    )
    if in_model and "predicted_value" in transfers.columns:
        transfers["predicted_value"] = pd.to_numeric(
            transfers["predicted_value"], errors="coerce"
        )

    transfers = transfers.dropna(
        subset=["from_club_name", "to_club_name", *MONEY_COLUMNS], how="all"
    )

    with st.container(border=True):
        st.subheader("Transfer history")
        if transfers.empty:
            st.caption("No transfers recorded for this player.")
        else:
            display_cols = [
                "transfer_date",
                "from_club_name",
                "to_club_name",
                *MONEY_COLUMNS,
            ]

            if in_model and "predicted_value" in transfers.columns:
                display_cols.append("predicted_value")

            st.dataframe(
                transfers.sort_values("transfer_date", ascending=False)[display_cols],
                hide_index=True,
                width="stretch",
                column_config={
                    "transfer_date": st.column_config.DateColumn(
                        "Date", format="YYYY-MM-DD"
                    ),
                    "from_club_name": "From",
                    "to_club_name": "To",
                    "transfer_fee": st.column_config.NumberColumn(
                        "Fee (€)", format="localized"
                    ),
                    "market_value_in_eur": st.column_config.NumberColumn(
                        "Market value at transfer (€)", format="localized"
                    ),
                    **predictions_configs,
                },
            )

def page_model():
    st.title("Model")

    st.markdown("""
        The model predicts a player's next Transfermarkt value from their previous
        value and recent playing record. Two LightGBM models sit behind it:
        
        - `lgb_delta` is used when the player already has a valuation and predicts how
        much that value will move, so the prediction is the last value plus that move.
        - `lgb_no_hist` is used when there is no previous valuation and estimates the
        value from the rest of the profile.
        """)

    st.markdown("""
        Along with the previous value, the model uses age, league, minutes, goals and
        the other counting stats from the last year, and the number of days since the
        last valuation. The model is trained on the log of the valuem, so the scale is
        consistent across all player values.
        """)

    st.markdown("""
        Training valuations stop at 30 June 2024, which is where the model line starts
        on a player's page, and up to that date it matches the Transfermarkt line. After
        it, each prediction starts from the real previous Transfermarkt value and only
        covers the next valuation, on dates the model did not see during training.
        """)

    st.subheader("Scoring")

    st.markdown("""
        | Score | What it measures |
        |---|---|
        | **MedAPE %** | The median absolute percentage error, after converting back to euros. 14% means half of the predictions are within 14% of the true value. |
        | **Log RMSE** | The root mean squared error on the log scale, which is the score the model was tuned to reduce. Large misses count for more here than in the median. |
        | **Bias** | The average of predicted minus actual on the log scale. Negative means the model tends to come in low, and -0.06 is about 6% too low. |

        Everything is scored on the log scale because valuations run from tens of
        thousands of euros to well over €100M, and a score in raw euros would be decided
        by the most expensive players. Lower is better for MedAPE and log RMSE, and a
        bias closer to zero is better.
        """)

    st.subheader("Results")

    st.markdown("""
        #### Players who already have a valuation

        Repeating the previous value, with the median as a fallback when there is none,
        is already a strong baseline at a 20% median error. `lgb-hybrid-delta` brings
        that down to 13.61%, about a third lower, although the four models that use the
        previous value are close to each other and the delta model is ahead by less than
        a percentage point. All four come in slightly low, while the baseline comes in
        slightly high with much larger errors. These scores are from the validation
        split.

        | Model | MedAPE % | Log RMSE | Bias |
        |---|:---:|:---:|:---:|
        | `previous-value-and-median-fallback` | 20.00 | 0.5514 | **0.0284** |
        | `hgb-with-history` | 14.29 | 0.4232 | -0.0628 |
        | `lgb-with-history` | 14.05 | 0.4143 | -0.0599 |
        | `lgb-hybrid` | 14.03 | 0.4058 | -0.0469 |
        | `lgb-hybrid-delta` | **13.61** | **0.4031** | -0.0437 |
        """)

    st.markdown("""
        #### Players with no previous valuation

        These players are much harder, because the model only has age, league and the
        recent playing record. LightGBM was the best of the boosted models on all three
        scores, with a median error of 44.78% against 81.82% for the dummy, and it is
        the model used when there is no previous value. It comes in low by about 25% on
        average. These scores are also from the validation split.

        | Model | MedAPE % | Log RMSE | Bias |
        |---|:---:|:---:|:---:|
        | `DummyRegressor` (median) | 81.82 | 1.6890 | -0.5933 |
        | `GradientBoostingRegressor` | 52.63 | 0.9271 | -0.3004 |
        | `HistGradientBoostingRegressor` | 46.62 | 0.8593 | -0.3033 |
        | `LightGBM` | **44.78** | **0.8326** | **-0.2833** |
        """)

    st.markdown("""
        #### Held-out test

        The final model is a lightly tuned version of `lgb-hybrid-delta`. Early stopping
        and the Optuna search both used the validation split, so its scores are optimistic, 
        while the test split was scored once at the end. Compared with validation, the median 
        error moves by half a point, log RMSE rises about 9% (0.4015 to 0.4387), so the larger 
        misses got a bit worse, and the bias goes from about 4% too low to about 6% too low. 
        The test scores are still better than the baseline's 20% median error and 0.551 log RMSE, 
        although those baseline numbers come from the validation split because it was not run again 
        on test.

        | Split | Model | MedAPE % | Log RMSE | Bias |
        |---|---|:---:|:---:|:---:|
        | Validation | `lgb-hybrid-delta-tuned` | 13.60 | 0.4015 | -0.0415 |
        | Test | `lgb-hybrid-delta-final` | 14.10 | 0.4387 | -0.0604 |
        """)

    st.subheader("Residuals")

    predictions = read_serving_parquet(
        "predictions", columns=["player_id", "date", "predicted_value"]
    )
    valuations = read_serving_parquet(
        "valuations", columns=["player_id", "date", "market_value_in_eur"]
    )
    players = read_serving_parquet("players", columns=["player_id", "name", "position"])

    pred_eval = pd.merge(
        predictions, valuations, on=["player_id", "date"], how="inner"
    ).merge(players[["player_id", "name", "position"]], on="player_id", how="left")

    pred_eval["date"] = pd.to_datetime(pred_eval["date"], errors="coerce").astype(
        "datetime64[ns]"
    )
    pred_eval["market_value_in_eur"] = pd.to_numeric(
        pred_eval["market_value_in_eur"], errors="coerce"
    )
    pred_eval["predicted_value"] = pd.to_numeric(
        pred_eval["predicted_value"], errors="coerce"
    )
    pred_eval = pred_eval.dropna(
        subset=["market_value_in_eur", "predicted_value", "date"]
    )

    test_df = pred_eval[pred_eval["date"] >= pd.to_datetime("2025-07-01")].copy()
    test_df["residual"] = test_df["predicted_value"] - test_df["market_value_in_eur"]

    fig_res = px.scatter(
        test_df,
        x="predicted_value",
        y="residual",
        color="position",
        hover_name="name",
        labels={
            "predicted_value": "Predicted Value (€)",
            "residual": "Residual (Predicted - Actual) (€)",
            "position": "Position",
        },
        opacity=0.7,
        color_discrete_sequence=PALLETE,
    )

    fig_res.add_shape(
        type="line",
        x0=test_df["predicted_value"].min(),
        y0=0,
        x1=test_df["predicted_value"].max(),
        y1=0,
        line=dict(color=ORANGE, dash="dash", width=2),
    )

    fig_res.update_traces(
        hovertemplate="<b>%{hovertext}</b><br>Predicted: €%{x:,.0f}<br>Residual: €%{y:,.0f}<extra></extra>"
    )
    fig_res.update_xaxes(tickformat=",.0f")
    fig_res.update_yaxes(tickformat=",.0f")
    st.plotly_chart(fig_res, width="stretch")

    st.caption(
        "Test residuals of the final model, in euros. "
        "A point below zero means the prediction came in too low."
    )
    st.markdown(f"**Mean Test Residual:** {format_money(test_df['residual'].mean())}")

    st.markdown("""
        Each point is a test prediction, the dashed line is where the prediction matches
        the actual value, and the colour is the player's position. The spread widens as
        the predicted value rises because the axis is in euros: a €10M miss is a
        doubling on a €10M player and about 10% on a €100M player, so the right-hand
        side looks worse than the 14% median error suggests, and the 6% low bias is too
        small to see at all. The parallel stripes between about €20M and €80M come from
        Transfermarkt values sitting on a short list of round numbers.
        """)

    st.markdown("""
        Most of the points far from the cloud are below the line. The lowest is an
        attacker predicted under €20M with a residual near -€58M, so their real value was
        around €75M, and a few other attackers and midfielders are €30M to €50M too
        low, which might be after a transfer, an injury or a breakout that the model 
        cannot see. The largest point above the line is Lamine Yamal, predicted at near €240M, 
        which is about €40M too high. There are only a handful of players past €150M,
        and nothing stops a prediction from going past the highest value the model saw
        in training.
        """)

    st.subheader("Conclusion")

    st.markdown("""
        On the test split, which was not used for tuning or early stopping, the median
        error is 14.10%, the log RMSE is 0.4387 and the bias is -0.0604. When a previous
        value exists the model tracks the next Transfermarkt value well, although most
        of that accuracy comes from the previous value itself, and with no previous
        value the median error is about 45%.

        The model stays close to the previous value, the way Transfermarkt itself tends
        to, so a transfer, an injury or a breakout is invisible to it, and it comes in
        about 6% low on average. There are few players that are near €200M, the highest
        value in the data, so a prediction up there can run past the real value, and
        predictions are not capped. The data is a snapshot from Transfermarkt that does
        not update.
        """)


def page_about():
    st.title("About Transferformance")
    st.markdown("""
        Transferformance is a tool for analyzing football player market values and transfer histories.
        It leverages data from Transfermarkt and applies machine learning models to predict player valuations.
        """)


ABOUT = st.Page(page_about, title="About")
OVERVIEW = st.Page(page_overview, title="Overview", default=True)
SEARCH = st.Page(page_search, title="Player Search", url_path="search")
MODEL = st.Page(page_model, title="Model", url_path="model")
PLAYER = st.Page(page_player, title="Player", url_path="player")

page = st.navigation([OVERVIEW, SEARCH, PLAYER, MODEL, ABOUT], position="hidden")
with st.sidebar:
    st.title("Transferformance")
    st.page_link(OVERVIEW)
    st.page_link(SEARCH)
    st.page_link(MODEL)
    st.page_link(ABOUT)
page.run()
