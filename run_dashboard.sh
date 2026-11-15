#!/usr/bin/env bash
# Start the dashboard, but only if the environment is installed and every
# serving file exists. Extra arguments are passed on to `streamlit run`.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_DIR=".venv"
APP_PATH="src/app/main.py"
SERVING_FILES=(players valuations records transfers clubs_and_competitions predictions)

fail() {
    echo "Error: $1" >&2
    exit 1
}

PYTHON="$VENV_DIR/bin/python"
[[ -x "$PYTHON" ]] || fail "No environment found at $VENV_DIR. Run 'uv sync' first."

"$PYTHON" -c "import streamlit" 2>/dev/null ||
    fail "Streamlit is not installed in $VENV_DIR. Run 'uv sync' first."

SERVING_DIR=$("$PYTHON" -c "from transferformance.configs import DIR_SRC_APP_SERVING; print(DIR_SRC_APP_SERVING)" 2>/dev/null | tail -n 1) ||
    fail "The transferformance package is not installed in $VENV_DIR. Run 'uv sync' first."

missing=()
for name in "${SERVING_FILES[@]}"; do
    [[ -f "$SERVING_DIR/$name.parquet" ]] || missing+=("$name.parquet")
done
if ((${#missing[@]} > 0)); then
    fail "Missing serving files in $SERVING_DIR: ${missing[*]}. Run the pipeline first (./run_pipeline.sh)."
fi

[[ -f "$APP_PATH" ]] || fail "App file not found at $APP_PATH."

exec "$PYTHON" -m streamlit run "$APP_PATH" "$@"