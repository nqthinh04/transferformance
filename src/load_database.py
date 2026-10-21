from pathlib import Path
from loguru import logger
import requests
from configs import URL_DB, HEADERS, CHUNK_SIZE

def download_database(url: str, save_path: Path, cached: bool = True) -> bool:
    if save_path.exists() and save_path.stat().st_size > 0 and cached:
        logger.info(f"Database existed at {save_path.absolute()} and cache was enabled. Skipping download")
        return True

    save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(
            url=url, headers=HEADERS, stream=True, timeout=(3.05, 27)
        ) as resp:
            resp.raise_for_status()

            logger.info(f"Downloading database from {url}, saving at {save_path.absolute()}")
            with open(save_path, "wb") as fout:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    fout.write(chunk)

            logger.info(f"Database saved at {save_path.absolute()}")
        return True

    except (OSError, requests.RequestException) as err:
        logger.error(f"Download failed, removing leftover files. Error: {err}")
        save_path.unlink(missing_ok=True)

        return False


if __name__ == "__main__":
    download_database(URL_DB, Path("./data/raw/transfermarkt.duckdb"))
