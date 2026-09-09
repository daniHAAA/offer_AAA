"""Seitenvorschau: rendert Seiten als PNG für die Oberfläche."""

from __future__ import annotations

from pathlib import Path

from .document import PdfToolError
from .edit import open_document


def render_page(
    source: str | Path,
    page_number: int,
    password: str | None = None,
    width: int = 900,
) -> bytes:
    """Rendert eine einzelne Seite als PNG mit der gewünschten Breite in Pixeln."""
    if width < 40 or width > 3000:
        raise PdfToolError("Die Vorschaubreite muss zwischen 40 und 3000 Pixeln liegen.")

    document = open_document(source, password)
    try:
        if page_number < 1 or page_number > document.page_count:
            raise PdfToolError(f"Seite {page_number} gibt es nicht (1-{document.page_count}).")

        page = document[page_number - 1]
        # Massstab aus der Zielbreite ableiten, damit jede Vorschau gleich breit wird.
        scale = width / page.rect.width if page.rect.width else 1.0
        pixmap = page.get_pixmap(matrix=_scale_matrix(scale), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def _scale_matrix(scale: float):
    import pymupdf

    return pymupdf.Matrix(scale, scale)
