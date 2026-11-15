#!/usr/bin/env bash
# Exit immediately if any command fails
set -e

echo "==> 1. Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add uv to the current shell session PATH (installed to ~/.local/bin by default)
export PATH="$HOME/.local/bin:$PATH"

echo "==> 2. Cloning repository..."
git clone https://github.com/nqthinh04/transferformance.git
cd transferformance

echo "==> 3. Syncing project dependencies with uv..."
uv sync

echo "==> 4. Running pipeline: Raw download..."
uv run python -m transferformance.raw.download --refresh

echo "==> 5. Running pipeline: Interim build..."
uv run python -m transferformance.interim.build

echo "==> 6. Running pipeline: Processed build..."
uv run python -m transferformance.processed.build --hist

echo "==> 7. Running pipeline: Serving database build..."
uv run python -m transferformance.serving.build_from_database

echo "==> 8. Running pipeline: Serving model build..."
uv run python -m transferformance.serving.build_from_model

echo "==> 9. Launching Streamlit app..."
uv run streamlit run ./src/app/main.py