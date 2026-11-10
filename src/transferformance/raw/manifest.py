import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class ManifestEntry:
    url: str
    sha256: str
    size_in_bytes: int
    downloaded_at_utc: str
    last_modified_at_utc: str | None

def read_manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text()) if path.exists() else {}

def write_manifest(path: Path, key: str, entry: ManifestEntry):
    manifest = read_manifest(path)
    manifest[key] = asdict(entry)

    path.parent.mkdir(parents=True, exist_ok=True)

    path_tmp = path.with_name(path.name + ".tmp")
    path_tmp.write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )
    path_tmp.replace(path)