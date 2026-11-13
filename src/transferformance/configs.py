from pathlib import Path

URL_DATABASE_TRANSFERMARKT = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.duckdb"

DIR_PROJECT_ROOT = Path(__file__).resolve().parents[2]

PATH_RAW_DATA = DIR_PROJECT_ROOT / "data" / "raw" / "transfermarkt-datasets.duckdb"
PATH_INTERIM_DATA = DIR_PROJECT_ROOT / "data" / "interim" / "interim.parquet"
PATH_PROCESSED_DATA = DIR_PROJECT_ROOT / "data" / "processed" / "processed.parquet"
DIR_PROCESSED_SPLITS = DIR_PROJECT_ROOT / "data" / "processed" / "splits"

DIR_ROOT_MODEL = DIR_PROJECT_ROOT / "model"

DIR_SRC = DIR_PROJECT_ROOT / "src"
DIR_SRC_MAIN = DIR_SRC / "transferformance"
DIR_SRC_INTERIM = DIR_SRC_MAIN / "interim"
DIR_SRC_APP = DIR_SRC / "app"
DIR_SRC_APP_SERVING = DIR_SRC_APP / "serving"

DEFAULT_WINDOW_IN_DAYS = 365
