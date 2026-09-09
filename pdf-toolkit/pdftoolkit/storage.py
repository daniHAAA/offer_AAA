"""Arbeitsbereich je Browser-Sitzung.

Hochgeladene und erzeugte Dateien liegen in einem Ordner pro Sitzung und
werden über eine zufällige ID angesprochen. Der Originalname landet nur im
Manifest -- so kann ein Dateiname niemals aus dem Ordner herausführen
(``../../etc/passwd`` und Konsorten).

Ein Ergebnis wird wie eine hochgeladene Datei registriert. Dadurch lassen
sich Schritte verketten: zusammenfügen, dann nummerieren, dann schützen --
ohne zwischendurch herunter- und wieder hochzuladen.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

_SAFE_NAME = re.compile(r"[^\w.\- ]+", re.UNICODE)
MANIFEST_NAME = "manifest.json"


def safe_filename(name: str, fallback: str = "dokument.pdf") -> str:
    """Entschärft einen Dateinamen für die Anzeige und den Download."""
    cleaned = _SAFE_NAME.sub("_", Path(name or "").name).strip(" ._")
    return cleaned[:120] or fallback


@dataclass
class StoredFile:
    id: str
    name: str
    kind: str          # "upload" oder "result"
    size: int
    created: float
    origin: str = ""   # welches Werkzeug die Datei erzeugt hat

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "created": self.created,
            "origin": self.origin,
            "is_pdf": self.name.lower().endswith(".pdf"),
        }


class Workspace:
    """Ein Ordner mit Manifest -- alles, was eine Sitzung an Dateien hat."""

    def __init__(self, root: Path, workspace_id: str) -> None:
        self.id = workspace_id
        self.root = Path(root) / workspace_id
        self.files_dir = self.root / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._manifest = self.root / MANIFEST_NAME

    # -- Lesen ---------------------------------------------------------

    def list_files(self) -> list[StoredFile]:
        data = self._read_manifest()
        entries = [StoredFile(**item) for item in data.get("files", [])]
        return sorted(entries, key=lambda item: item.created, reverse=True)

    def get(self, file_id: str) -> StoredFile | None:
        return next((item for item in self.list_files() if item.id == file_id), None)

    def path_of(self, file_id: str) -> Path | None:
        """Liefert den Pfad zu einer Datei -- nur wenn sie wirklich im Manifest steht."""
        entry = self.get(file_id)
        if not entry:
            return None
        path = self.files_dir / f"{entry.id}{_suffix(entry.name)}"
        return path if path.is_file() else None

    # -- Schreiben -----------------------------------------------------

    def add_upload(self, stream, filename: str) -> StoredFile:
        """Nimmt einen hochgeladenen Datei-Stream auf."""
        name = safe_filename(filename)
        file_id = secrets.token_hex(8)
        target = self.files_dir / f"{file_id}{_suffix(name)}"
        stream.save(str(target))
        return self._register(file_id, name, "upload", target, origin="Upload")

    def add_result(self, source: Path, name: str, origin: str) -> StoredFile:
        """Übernimmt eine erzeugte Datei in den Arbeitsbereich."""
        name = safe_filename(name)
        file_id = secrets.token_hex(8)
        target = self.files_dir / f"{file_id}{_suffix(name)}"
        if Path(source) != target:
            shutil.move(str(source), str(target))
        return self._register(file_id, name, "result", target, origin=origin)

    def temp_dir(self, prefix: str = "work") -> Path:
        """Kurzlebiger Ordner für Zwischenschritte, etwa vor dem Packen einer ZIP-Datei."""
        path = self.root / "tmp" / f"{prefix}_{secrets.token_hex(4)}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def delete(self, file_id: str) -> bool:
        data = self._read_manifest()
        remaining = [item for item in data.get("files", []) if item["id"] != file_id]
        if len(remaining) == len(data.get("files", [])):
            return False

        for path in self.files_dir.glob(f"{file_id}.*"):
            path.unlink(missing_ok=True)

        data["files"] = remaining
        self._write_manifest(data)
        return True

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    # -- Innereien -----------------------------------------------------

    def _register(self, file_id: str, name: str, kind: str, path: Path, origin: str) -> StoredFile:
        entry = StoredFile(
            id=file_id,
            name=name,
            kind=kind,
            size=path.stat().st_size,
            created=time.time(),
            origin=origin,
        )
        data = self._read_manifest()
        data.setdefault("files", []).append(entry.__dict__)
        self._write_manifest(data)
        return entry

    def _read_manifest(self) -> dict:
        if not self._manifest.is_file():
            return {"files": []}
        try:
            return json.loads(self._manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"files": []}

    def _write_manifest(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        # Erst daneben schreiben, dann umbenennen: ein Absturz mittendrin
        # hinterlässt so kein halbes Manifest.
        temporary = self._manifest.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self._manifest)


def cleanup_old_workspaces(root: Path, max_age_hours: float) -> int:
    """Räumt Arbeitsbereiche weg, die länger nicht angefasst wurden."""
    root = Path(root)
    if not root.is_dir() or max_age_hours <= 0:
        return 0

    cutoff = time.time() - max_age_hours * 3600
    removed = 0

    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        manifest = candidate / MANIFEST_NAME
        reference = manifest if manifest.exists() else candidate
        try:
            if reference.stat().st_mtime < cutoff:
                shutil.rmtree(candidate, ignore_errors=True)
                removed += 1
        except OSError:
            continue

    return removed


def _suffix(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"
