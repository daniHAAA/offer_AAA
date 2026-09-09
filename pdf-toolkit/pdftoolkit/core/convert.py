"""Umwandeln: PDF nach Word, Text, Bild -- und Bilder zurück nach PDF."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .document import PdfToolError
from .edit import open_document
from .pages import parse_page_selection

# pdf2docx zieht schwere Abhängigkeiten nach. Der Import passiert deshalb erst
# beim ersten Word-Export -- ohne ihn läuft der Rest des Toolkits normal weiter.
_WORD_HINT = (
    "Für den Word-Export fehlt das Paket pdf2docx. "
    "Nachinstallieren mit: pip install pdf2docx"
)


def pdf_to_word(
    source: str | Path,
    target: str | Path,
    password: str | None = None,
    selection: str | None = None,
) -> Path:
    """Wandelt ein PDF in eine .docx-Datei.

    pdf2docx rekonstruiert Absätze, Tabellen und Bilder aus der Anordnung auf
    der Seite. Bei gescannten PDFs ohne Textebene entsteht deshalb ein
    Dokument voller Bilder -- dort hilft nur vorherige Texterkennung.
    """
    try:
        from pdf2docx import Converter
    except ImportError as exc:
        raise PdfToolError(_WORD_HINT) from exc

    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    document = open_document(source, password)
    try:
        page_count = document.page_count
        indices = parse_page_selection(selection, page_count) if selection else None
    finally:
        document.close()

    converter = Converter(str(source), password=password or None)
    try:
        converter.convert(str(target), pages=indices)
    except Exception as exc:
        raise PdfToolError(f"Die Umwandlung nach Word ist gescheitert: {exc}") from exc
    finally:
        converter.close()

    if not target.is_file():
        raise PdfToolError("Die Word-Datei wurde nicht erzeugt.")
    return target


def pdf_to_text(
    source: str | Path,
    target: str | Path | None = None,
    password: str | None = None,
    selection: str | None = None,
    layout: bool = False,
) -> str:
    """Zieht den Text heraus. ``layout=True`` erhält die Anordnung grob mit Leerzeichen."""
    document = open_document(source, password)
    try:
        indices = parse_page_selection(selection, document.page_count)
        mode = "text" if not layout else "blocks"

        chunks: list[str] = []
        for index in indices:
            page = document[index]
            if mode == "text":
                chunks.append(page.get_text("text"))
            else:
                blocks = sorted(page.get_text("blocks"), key=lambda block: (block[1], block[0]))
                chunks.append("\n".join(block[4].strip() for block in blocks if block[4].strip()))

        content = "\n\n".join(chunk.rstrip() for chunk in chunks).strip() + "\n"
    finally:
        document.close()

    if target:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    return content


def pdf_to_images(
    source: str | Path,
    output_dir: str | Path,
    password: str | None = None,
    selection: str | None = None,
    dpi: int = 150,
    image_format: str = "png",
    stem: str | None = None,
) -> list[Path]:
    """Rendert Seiten als Bilddateien -- eine Datei je Seite."""
    if dpi < 36 or dpi > 600:
        raise PdfToolError("Die Auflösung muss zwischen 36 und 600 dpi liegen.")

    image_format = image_format.lower().lstrip(".")
    if image_format not in {"png", "jpg", "jpeg"}:
        raise PdfToolError("Unterstützt werden png und jpg.")

    source = Path(source)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = stem or source.stem

    document = open_document(source, password)
    try:
        indices = parse_page_selection(selection, document.page_count)
        results: list[Path] = []

        for index in indices:
            pixmap = document[index].get_pixmap(dpi=dpi)
            path = output_dir / f"{base}_S{index + 1:03d}.{image_format}"
            if image_format in {"jpg", "jpeg"}:
                # JPEG kennt keine Transparenz -- vorher auf RGB reduzieren.
                pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
            pixmap.save(str(path))
            results.append(path)

        return results
    finally:
        document.close()


def images_to_pdf(sources: list[str | Path], target: str | Path) -> Path:
    """Baut aus Bildern ein PDF -- jede Datei wird eine Seite in Originalgrösse."""
    if not sources:
        raise PdfToolError("Es wurde kein Bild übergeben.")

    document = pymupdf.open()
    try:
        for source in sources:
            source = Path(source)
            if not source.is_file():
                raise PdfToolError(f"Bild nicht gefunden: {source.name}")
            try:
                image_pdf = pymupdf.open(str(source))
                pdf_bytes = image_pdf.convert_to_pdf()
                image_pdf.close()
            except Exception as exc:
                raise PdfToolError(f"{source.name} ist kein lesbares Bild: {exc}") from exc

            page_pdf = pymupdf.open("pdf", pdf_bytes)
            document.insert_pdf(page_pdf)
            page_pdf.close()

        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(target), garbage=3, deflate=True)
        return target
    finally:
        document.close()
