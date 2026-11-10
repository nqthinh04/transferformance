from pathlib import Path

URL_DATABASE_TRANSFERMARKT = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.duckdb"

DIR_PROJECT_ROOT = Path(__file__).resolve().parents[2]

PATH_RAW_DATA = DIR_PROJECT_ROOT / "data" / "raw" / "transfermarkt-datasets.duckdb"
PATH_MANIFEST = DIR_PROJECT_ROOT / "data" / "raw" / "manifest.json"

PATH_INTERIM_DATA = DIR_PROJECT_ROOT / "data" / "interim" / "interim.parquet"