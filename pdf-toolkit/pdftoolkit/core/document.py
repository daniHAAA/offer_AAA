"""Gemeinsame Basis: PDFs öffnen, prüfen und beschreiben.

Alle Werkzeuge gehen durch ``open_reader``. Dadurch gibt es genau eine
Stelle, die kaputte Dateien und Passwortschutz abfängt -- die Werkzeuge
selbst müssen sich darum nicht kümmern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pypdf
from pypdf.errors import PdfReadError


class PdfToolError(Exception):
    """Fehler, dessen Text direkt der Nutzerin bzw. dem Nutzer gezeigt werden darf."""


class PasswordRequiredError(PdfToolError):
    """Das Dokument ist verschlüsselt und das Passwort fehlt oder stimmt nicht."""


@dataclass
class PageInfo:
    number: int          # 1-basiert, wie im Viewer
    width: float         # in Punkt (1 pt = 1/72 Zoll)
    height: float
    rotation: int


@dataclass
class DocumentInfo:
    filename: str
    page_count: int
    encrypted: bool
    has_form: bool
    file_size: int
    title: str = ""
    author: str = ""
    pages: list[PageInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "page_count": self.page_count,
            "encrypted": self.encrypted,
            "has_form": self.has_form,
            "file_size": self.file_size,
            "title": self.title,
            "author": self.author,
            "pages": [
                {
                    "number": page.number,
                    "width": round(page.width, 1),
                    "height": round(page.height, 1),
                    "rotation": page.rotation,
                    "landscape": page.width > page.height,
                }
                for page in self.pages
            ],
        }


def open_reader(path: str | Path, password: str | None = None) -> pypdf.PdfReader:
    """Öffnet ein PDF und entschlüsselt es bei Bedarf.

    Wirft ``PasswordRequiredError``, wenn das Dokument geschützt ist und das
    übergebene Passwort nicht passt -- die Oberfläche kann dann gezielt nach
    dem Passwort fragen, statt einen Stacktrace zu zeigen.
    """
    path = Path(path)
    if not path.is_file():
        raise PdfToolError(f"Datei nicht gefunden: {path.name}")

    try:
        reader = pypdf.PdfReader(str(path))
    except PdfReadError as exc:
        raise PdfToolError(f"{path.name} lässt sich nicht als PDF lesen: {exc}") from exc

    if reader.is_encrypted:
        try:
            opened = reader.decrypt(password or "")
        except (NotImplementedError, PdfReadError) as exc:
            raise PasswordRequiredError(
                f"{path.name} nutzt eine nicht unterstützte Verschlüsselung: {exc}"
            ) from exc
        if opened == 0:
            raise PasswordRequiredError(f"{path.name} ist passwortgeschützt.")

    return reader


def describe(path: str | Path, password: str | None = None) -> DocumentInfo:
    """Liest die Eckdaten eines PDFs -- Grundlage für Vorschau und Formularansicht."""
    path = Path(path)
    reader = open_reader(path, password)

    metadata = reader.metadata or {}
    pages = [
        PageInfo(
            number=index + 1,
            width=float(page.mediabox.width),
            height=float(page.mediabox.height),
            rotation=int(page.get("/Rotate", 0) or 0) % 360,
        )
        for index, page in enumerate(reader.pages)
    ]

    return DocumentInfo(
        filename=path.name,
        page_count=len(reader.pages),
        encrypted=reader.is_encrypted,
        has_form=bool(reader.get_fields()),
        file_size=path.stat().st_size,
        title=str(metadata.get("/Title", "") or ""),
        author=str(metadata.get("/Author", "") or ""),
        pages=pages,
    )


def write_pdf(writer: pypdf.PdfWriter, target: str | Path) -> Path:
    """Schreibt einen Writer auf die Platte und gibt den Pfad zurück."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        writer.write(handle)
    return target
