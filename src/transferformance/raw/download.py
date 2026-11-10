from transferformance.configs import (
    PATH_MANIFEST,
    PATH_RAW_DATA,
    URL_DATABASE_TRANSFERMARKT,
)

from transferformance.raw.manifest import ManifestEntry, read_manifest, write_manifest

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from loguru import logger

HEADERS = {"User-Agent": "transferformance/0.1", "Accept-Encoding": "identity"}
CHUNK_SIZE = 1 << 20
TIMEOUT_IN_SEC = (10, 30)


class DownloadError(Exception):
    pass


def _stream_to_file(resp: requests.Response, path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size_in_bytes = 0

    with path.open("wb") as fout:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            fout.write(chunk)
            hasher.update(chunk)
            size_in_bytes += len(chunk)

    return hasher.hexdigest(), size_in_bytes


def _get_date_in_utc(http_date: str | None) -> str | None:
    if not http_date:
        return None

    try:
        return parsedate_to_datetime(http_date).isoformat()
    except (TypeError, ValueError):
        return None


def _check_size(resp: requests.Response, size_in_bytes: int):
    expected_size_in_bytes = resp.headers.get("Content-Length")
    encoding = resp.headers.get("Content-Encoding", "identity").lower()

    if (encoding != "identity") or (not expected_size_in_bytes):
        return

    if int(expected_size_in_bytes) != size_in_bytes:
        raise DownloadError(
            f"Incomplete download: Expected {expected_size_in_bytes}, got {size_in_bytes}"
        )


def download(url: str, save_path: Path, manifest_path: Path, refresh: bool = False):
    if save_path.exists() and not refresh:
        if manifest_path.exists() and read_manifest(manifest_path):
            logger.info(f"{save_path} already exists, skipping download")
            return

        logger.warning(
            f"{save_path} exists but has no manifest entry, downloading again"
        )

    save_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = save_path.with_name(save_path.name + ".part")

    logger.info(f"Download {url} to {save_path}")

    try:
        with requests.get(
            url=url, headers=HEADERS, stream=True, timeout=TIMEOUT_IN_SEC
        ) as resp:
            resp.raise_for_status()

            sha256, size_in_bytes = _stream_to_file(resp, tmp_path)
            _check_size(resp, size_in_bytes)

            last_modified_at_utc = _get_date_in_utc(resp.headers.get("Last-Modified"))

        tmp_path.replace(save_path)

    finally:
        tmp_path.unlink(missing_ok=True)

    write_manifest(
        path=manifest_path,
        key=save_path.name,
        entry=ManifestEntry(
            url=url,
            sha256=sha256,
            size_in_bytes=size_in_bytes,
            downloaded_at_utc=datetime.now(timezone.utc).isoformat(),
            last_modified_at_utc=last_modified_at_utc,
        ),
    )

    logger.info(
        f"Saved at {save_path.absolute()}. Size (in bytes): {size_in_bytes}, SHA256: {sha256}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download `dcaribou/transfermarkt-datasets`'s DuckDB database"
    )
    parser.add_argument(
        "--url", type=str, default=URL_DATABASE_TRANSFERMARKT, help="Source URL"
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=PATH_RAW_DATA,
        help="Where to save the database file",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PATH_MANIFEST,
        help="Where to save the manifest JSON",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download again even if the database file exists",
    )
    args = parser.parse_args()

    try:
        download(
            url=args.url,
            save_path=args.path,
            manifest_path=args.manifest,
            refresh=args.refresh,
        )
    except (DownloadError, OSError, requests.RequestException) as err:
        logger.error("Download failed: {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())