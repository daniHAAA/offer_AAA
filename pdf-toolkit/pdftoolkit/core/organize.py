"""Seiten organisieren: löschen, drehen, umsortieren, einfügen.

Alle Funktionen laufen auf ``apply_layout`` zusammen. Die Oberfläche schickt
nach dem Ziehen und Drehen einfach den fertigen Seitenplan -- Server und
Anzeige können so nicht auseinanderlaufen.
"""

from __future__ import annotations

from pathlib import Path

import pypdf

from .document import PdfToolError, open_reader, write_pdf
from .pages import parse_page_selection


def apply_layout(
    source: str | Path,
    target: str | Path,
    layout: list[dict],
    password: str | None = None,
) -> Path:
    """Baut das Dokument gemäss Plan neu auf.

    ``layout`` ist eine Liste von ``{"page": 1-basierte Nummer, "rotate": Grad}``.
    Reihenfolge der Liste = Reihenfolge im Ergebnis; nicht gelistete Seiten
    fallen weg. ``rotate`` ist relativ zur bisherigen Ausrichtung.
    """
    reader = open_reader(source, password)
    page_count = len(reader.pages)

    if not layout:
        raise PdfToolError("Der Seitenplan ist leer -- so bliebe kein Blatt übrig.")

    writer = pypdf.PdfWriter()

    for entry in layout:
        number = int(entry.get("page", 0))
        if number < 1 or number > page_count:
            raise PdfToolError(f"Seite {number} gibt es im Dokument nicht (1-{page_count}).")

        page = reader.pages[number - 1]
        rotation = int(entry.get("rotate", 0) or 0)
        if rotation % 90 != 0:
            raise PdfToolError("Gedreht wird in Schritten von 90 Grad.")
        if rotation:
            page.rotate(rotation % 360)

        writer.add_page(page)

    return write_pdf(writer, target)


def delete_pages(
    source: str | Path,
    target: str | Path,
    selection: str,
    password: str | None = None,
) -> Path:
    """Entfernt die ausgewählten Seiten und behält den Rest in Reihenfolge."""
    reader = open_reader(source, password)
    page_count = len(reader.pages)

    to_remove = set(parse_page_selection(selection, page_count))
    keep = [index for index in range(page_count) if index not in to_remove]
    if not keep:
        raise PdfToolError("Es würden alle Seiten gelöscht -- mindestens eine muss bleiben.")

    return apply_layout(source, target, [{"page": index + 1} for index in keep], password)


def rotate_pages(
    source: str | Path,
    target: str | Path,
    selection: str,
    degrees: int,
    password: str | None = None,
) -> Path:
    """Dreht die ausgewählten Seiten, alle übrigen bleiben unangetastet."""
    reader = open_reader(source, password)
    page_count = len(reader.pages)
    chosen = set(parse_page_selection(selection, page_count))

    layout = [
        {"page": index + 1, "rotate": degrees if index in chosen else 0}
        for index in range(page_count)
    ]
    return apply_layout(source, target, layout, password)


def reorder_pages(
    source: str | Path,
    target: str | Path,
    order: str,
    password: str | None = None,
) -> Path:
    """Sortiert das Dokument nach einer Reihenfolge wie "3,1,2" oder "5-,1-4"."""
    reader = open_reader(source, password)
    indices = parse_page_selection(order, len(reader.pages))
    return apply_layout(source, target, [{"page": index + 1} for index in indices], password)


def insert_pdf(
    source: str | Path,
    insert: str | Path,
    target: str | Path,
    after_page: int,
    password: str | None = None,
    insert_password: str | None = None,
) -> Path:
    """Schiebt ein zweites PDF hinter Seite ``after_page`` ein (0 = ganz an den Anfang)."""
    base_reader = open_reader(source, password)
    extra_reader = open_reader(insert, insert_password)
    page_count = len(base_reader.pages)

    if after_page < 0 or after_page > page_count:
        raise PdfToolError(f"Einfügeposition {after_page} liegt ausserhalb von 0-{page_count}.")

    writer = pypdf.PdfWriter()
    for page in base_reader.pages[:after_page]:
        writer.add_page(page)
    for page in extra_reader.pages:
        writer.add_page(page)
    for page in base_reader.pages[after_page:]:
        writer.add_page(page)

    return write_pdf(writer, target)
