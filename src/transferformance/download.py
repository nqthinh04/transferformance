from transferformance.configs import (
    PATH_MANIFEST,
    PATH_RAW_DATA,
    URL_DATABASE_TRANSFERMARKT,
)

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from loguru import logger

HEADERS = {"User-Agent": "transferformance/0.1", "Accept-Encoding": "identity"}
CHUNK_SIZE = 1 << 20
TIMEOUT_SECONDS = 30


def write_manifest(
    manifest_path: Path,
    name: str,
    entry: dict,
) -> None:
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[name] = entry

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info(f"Manifest for {name} updated at {manifest_path}")


def _parse_http_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def _stream_to_file(resp: requests.Response, dest: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    file_size = 0
    with dest.open("wb") as fout:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            fout.write(chunk)
            hasher.update(chunk)
            file_size += len(chunk)
    return hasher.hexdigest(), file_size


def download(
    url: str = URL_DATABASE_TRANSFERMARKT,
    save_path: Path = PATH_RAW_DATA,
    refresh: bool = False,
    manifest_path: Path = PATH_MANIFEST,
) -> bool:
    """
    Download from `url` to `save_path` and record it in the manifest at `manifest_path`.

    Parameters
    ---
    url: str
        File's download URL.

    save_path: Path
        Destination path for the file downloaded from the URL.

    refresh: bool
        Whether to re-download the file. If `refresh` is False and the file already exists at `save_path`, download is skipped.

    manifest_path: Path
        Destination path for the manifest file.

    Return
    ---
    bool
        Whether the download process was successful.
    """
    if save_path.exists() and not refresh:
        logger.info(f"File already exists at {save_path.absolute()}")
        return True

    save_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = save_path.with_name(save_path.name + ".part")

    try:
        logger.info(f"Downloading {url} to {temp_path.absolute()}")

        with requests.get(
            url, stream=True, headers=HEADERS, timeout=TIMEOUT_SECONDS
        ) as resp:
            resp.raise_for_status()
            expected_size = resp.headers.get("Content-Length")
            last_modified = resp.headers.get("Last-Modified")

            try:
                sha256, size = _stream_to_file(resp, temp_path)

                if expected_size and int(expected_size) != size:
                    raise IOError(
                        f"Incomplete download: expected {expected_size} bytes, got {size}"
                    )

                temp_path.replace(save_path)
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise

        logger.info(f"Saved {save_path.name} to {save_path.absolute()}")

        write_manifest(
            manifest_path=manifest_path,
            name=save_path.name,
            entry={
                "url": url,
                "sha256": sha256,
                "size_bytes": size,
                "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                "last_modified": _parse_http_date(last_modified),
            },
        )
    except (requests.RequestException, OSError) as err:
        logger.error(f"Download failed: {err}")
        return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download the Transfermarkt DuckDB dataset."
    )
    parser.add_argument("--url", default=URL_DATABASE_TRANSFERMARKT, help="source URL")
    parser.add_argument(
        "--path", type=Path, default=PATH_RAW_DATA, help="where to save the file"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="re-download even if the file exists"
    )
    args = parser.parse_args()

    return 0 if download(args.url, args.path, args.refresh) else 1


if __name__ == "__main__":
    sys.exit(main())
