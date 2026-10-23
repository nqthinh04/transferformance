from pathlib import Path

URL_DB = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.duckdb"
HEADERS = {"Accept-Encoding": "identity"}
CHUNK_SIZE = 1 << 20

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
DB_SAVE_PATH = PROJECT_ROOT_PATH / "data/raw/transfermarkt.duckdb"
