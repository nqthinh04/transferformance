import duckdb
from pathlib import Path
from loguru import logger
from src.constants import TRANSFERMARTK_DB_CHECKS
from src.configs import DB_SAVE_PATH

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

            cnt_warnings = 0

            for desc, sql_cmd in TRANSFERMARTK_DB_CHECKS['warnings'].items():
                bad_rows = con.execute(sql_cmd).fetchone()[0]

                if bad_rows:
                    logger.warning(f"Failed database check: {desc}. Found {bad_rows}")
                    cnt_warnings += 1
                else:
                    logger.info(f"Passed database check: {desc}")

            for desc, sql_cmd in TRANSFERMARTK_DB_CHECKS['infos'].items():
                info = con.execute(sql_cmd).fetchone()

                if info:
                    logger.info(f"Info: {desc}: {info}")

    except duckdb.Error as err:
        logger.error(f"Unable to access database at {db_path.absolute()}: {err}")
        return False

    logger.info(f"Database check completed with {cnt_warnings} warnings(s).")
    return True

if __name__ == "__main__":
    check_database(Path(DB_SAVE_PATH))