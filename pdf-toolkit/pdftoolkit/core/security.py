"""Schutz und Grösse: verschlüsseln, entschlüsseln, komprimieren."""

from __future__ import annotations

from pathlib import Path

import pypdf

from .document import PdfToolError, open_reader, write_pdf
from .edit import _save, open_document


def encrypt(
    source: str | Path,
    target: str | Path,
    user_password: str,
    owner_password: str | None = None,
    password: str | None = None,
    allow_printing: bool = True,
) -> Path:
    """Setzt ein Passwort (AES-256).

    ``user_password`` wird zum Öffnen gebraucht, ``owner_password`` erlaubt
    zusätzlich das Ändern der Rechte. Ohne Angabe wird das Nutzerpasswort
    für beides verwendet.
    """
    if not user_password:
        raise PdfToolError("Ohne Passwort lässt sich nichts verschlüsseln.")

    reader = open_reader(source, password)
    writer = pypdf.PdfWriter()
    writer.append_pages_from_reader(reader)

    permissions = pypdf.constants.UserAccessPermissions.R2 if allow_printing else 0
    writer.encrypt(
        user_password=user_password,
        owner_password=owner_password or user_password,
        permissions_flag=pypdf.constants.UserAccessPermissions.all()
        if allow_printing
        else pypdf.constants.UserAccessPermissions(permissions),
        algorithm="AES-256",
    )
    return write_pdf(writer, target)


def decrypt(source: str | Path, target: str | Path, password: str) -> Path:
    """Entfernt den Passwortschutz -- das richtige Passwort vorausgesetzt."""
    reader = open_reader(source, password)
    writer = pypdf.PdfWriter()
    writer.append_pages_from_reader(reader)
    return write_pdf(writer, target)


def compress(
    source: str | Path,
    target: str | Path,
    password: str | None = None,
    image_quality: int = 70,
    image_dpi: int = 150,
) -> dict:
    """Verkleinert die Datei: Streams neu packen, Bilder neu berechnen.

    Gibt die Grössen vorher/nachher zurück, damit sich der Nutzen beziffern
    lässt. Bringt die Bearbeitung nichts, bleibt die Originalgrösse stehen.
    """
    source, target = Path(source), Path(target)
    before = source.stat().st_size

    document = open_document(source, password)
    try:
        if 1 <= image_quality < 100:
            _shrink_images(document, image_quality, image_dpi)
        _save_compressed(document, target)
    finally:
        document.close()

    after = target.stat().st_size
    return {
        "before": before,
        "after": after,
        "saved": max(before - after, 0),
        "ratio": round(after / before, 3) if before else 1.0,
    }


def _shrink_images(document, quality: int, dpi: int) -> None:
    """Ersetzt eingebettete Bilder durch kleiner gerechnete JPEGs."""
    import pymupdf

    for page in document:
        for image in page.get_images(full=True):
            xref = image[0]
            try:
                pixmap = pymupdf.Pixmap(document, xref)
            except Exception:
                continue  # Maskenbilder und Exoten überspringen

            if pixmap.n - pixmap.alpha >= 4:  # CMYK
                pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
            if pixmap.alpha:
                pixmap = pymupdf.Pixmap(pixmap, 0)

            if pixmap.width * pixmap.height < 10_000:
                continue  # Kleinkram lohnt den Qualitätsverlust nicht

            try:
                document.update_stream(xref, b"")  # Platz im alten Stream freigeben
                page.replace_image(xref, pixmap=pixmap)
            except Exception:
                continue
            finally:
                pixmap = None


def _save_compressed(document, target: str | Path) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(
        str(target),
        garbage=4,       # verwaiste Objekte entfernen und zusammenfassen
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        clean=True,
    )
