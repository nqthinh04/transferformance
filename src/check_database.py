import duckdb
from pathlib import Path
from loguru import logger
from constants import TRANSFERMARTK_DB_CHECKS

def check_database(db_path: Path) -> bool:
    try:
        with duckdb.connect(db_path, read_only=True) as con:
            for desc, sql_cmd in TRANSFERMARTK_DB_CHECKS['errors'].items():
                bad_rows = con.execute(sql_cmd).fetchone()[0]

                if bad_rows:
                    logger.error(f"Failed database check: {desc}. Found {bad_rows}")
                    return False
                else:
                    logger.info(f"Passed database check: {desc}")

            for desc, sql_cmd in TRANSFERMARTK_DB_CHECKS['warnings'].items():
                bad_rows = con.execute(sql_cmd).fetchone()[0]

                if bad_rows:
                    logger.warning(f"Uncompleted database check: {desc}. Found {bad_rows}")
                else:
                    logger.info(f"Passed database check: {desc}")

            for desc, sql_cmd in TRANSFERMARTK_DB_CHECKS['infos'].items():
                info = con.execute(sql_cmd).fetchone()

                if info:
                    logger.info(f"Info: {desc}: {info}")

    except duckdb.Error as err:
        logger.error(f"Unable to access database at {db_path.absolute()}: {err}")
        return False

    logger.success("All database checks passed")
    return True

check_database(Path("data/raw/transfermarkt.duckdb"))