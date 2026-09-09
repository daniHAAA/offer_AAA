"""PDFs aufteilen -- nach Bereichen, in Einzelseiten oder in gleich grosse Blöcke."""

from __future__ import annotations

import re
from pathlib import Path

import pypdf

from .document import PdfToolError, open_reader, write_pdf
from .pages import format_page_selection, parse_page_selection

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def split_by_ranges(
    source: str | Path,
    output_dir: str | Path,
    ranges: list[str],
    password: str | None = None,
    stem: str | None = None,
) -> list[Path]:
    """Erzeugt pro Bereich eine eigene Datei ("1-3" und "4-" ergeben zwei PDFs)."""
    source = Path(source)
    reader = open_reader(source, password)
    page_count = len(reader.pages)

    cleaned = [item.strip() for item in ranges if item and item.strip()]
    if not cleaned:
        raise PdfToolError("Es wurde kein Seitenbereich angegeben.")

    base = _safe_stem(stem or source.stem)
    results: list[Path] = []

    for position, expression in enumerate(cleaned, start=1):
        indices = parse_page_selection(expression, page_count)
        writer = pypdf.PdfWriter()
        for index in indices:
            writer.add_page(reader.pages[index])

        label = _safe_stem(format_page_selection(indices)) or str(position)
        results.append(write_pdf(writer, Path(output_dir) / f"{base}_{position:02d}_S{label}.pdf"))

    return results


def split_every_page(
    source: str | Path,
    output_dir: str | Path,
    password: str | None = None,
    stem: str | None = None,
) -> list[Path]:
    """Zerlegt das Dokument in einzelne Seiten."""
    return split_into_chunks(source, output_dir, 1, password=password, stem=stem)


def split_into_chunks(
    source: str | Path,
    output_dir: str | Path,
    chunk_size: int,
    password: str | None = None,
    stem: str | None = None,
) -> list[Path]:
    """Teilt das Dokument in Blöcke fester Grösse (z. B. alle 10 Seiten)."""
    if chunk_size < 1:
        raise PdfToolError("Die Blockgrösse muss mindestens 1 Seite betragen.")

    source = Path(source)
    reader = open_reader(source, password)
    page_count = len(reader.pages)
    base = _safe_stem(stem or source.stem)
    results: list[Path] = []

    for position, start in enumerate(range(0, page_count, chunk_size), start=1):
        window = range(start, min(start + chunk_size, page_count))
        writer = pypdf.PdfWriter()
        for index in window:
            writer.add_page(reader.pages[index])

        label = format_page_selection(list(window))
        results.append(write_pdf(writer, Path(output_dir) / f"{base}_{position:02d}_S{label}.pdf"))

    return results


def extract_pages(
    source: str | Path,
    target: str | Path,
    selection: str,
    password: str | None = None,
) -> Path:
    """Zieht eine Auswahl in ein einziges neues Dokument -- der Klassiker "Seiten extrahieren"."""
    reader = open_reader(source, password)
    indices = parse_page_selection(selection, len(reader.pages))

    writer = pypdf.PdfWriter()
    for index in indices:
        writer.add_page(reader.pages[index])

    return write_pdf(writer, target)


def _safe_stem(value: str) -> str:
    """Macht aus beliebigem Text einen Dateinamen ohne Überraschungen."""
    return _UNSAFE_NAME.sub("_", value).strip("_")[:60]
