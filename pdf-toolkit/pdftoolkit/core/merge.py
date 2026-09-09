"""PDFs zusammenfügen."""

from __future__ import annotations

from pathlib import Path

import pypdf

from .document import PdfToolError, open_reader, write_pdf
from .pages import parse_page_selection


def merge_pdfs(
    sources: list[str | Path],
    target: str | Path,
    selections: list[str | None] | None = None,
    passwords: list[str | None] | None = None,
    add_bookmarks: bool = True,
) -> Path:
    """Hängt mehrere PDFs in der übergebenen Reihenfolge aneinander.

    ``selections`` erlaubt pro Datei eine Seitenangabe (z. B. nur "1-3" aus
    Dokument zwei). Mit ``add_bookmarks`` bekommt jedes Quelldokument ein
    Lesezeichen, damit die zusammengefügte Datei navigierbar bleibt.
    """
    if not sources:
        raise PdfToolError("Zum Zusammenfügen werden mindestens zwei PDFs gebraucht.")

    writer = pypdf.PdfWriter()

    for position, source in enumerate(sources):
        source = Path(source)
        password = passwords[position] if passwords and position < len(passwords) else None
        reader = open_reader(source, password)

        selection = selections[position] if selections and position < len(selections) else None
        indices = parse_page_selection(selection, len(reader.pages))

        first_page_of_source = len(writer.pages)
        for index in indices:
            writer.add_page(reader.pages[index])

        if add_bookmarks and indices:
            writer.add_outline_item(source.stem, first_page_of_source)

    if not writer.pages:
        raise PdfToolError("Die Auswahl ergibt kein einziges Blatt.")

    return write_pdf(writer, target)
