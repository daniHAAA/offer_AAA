"""PDF bearbeiten: Text, Bilder, Formen, Wasserzeichen, Schwärzen, Seitenzahlen.

Koordinaten kommen als Anteil der Seite (0.0-1.0). Das klingt umständlich,
löst aber ein echtes Problem: Die Oberfläche zeigt die Seite in einer
beliebigen Pixelgrösse. Ein Anteil bleibt bei jedem Zoom und jedem
Seitenformat richtig, absolute Pixel nicht.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .document import PasswordRequiredError, PdfToolError

# Die 14 Standardschriften jedes PDF-Betrachters -- keine Einbettung nötig.
FONTS = {
    "helvetica": "helv",
    "helvetica-bold": "hebo",
    "helvetica-oblique": "heit",
    "times": "tiro",
    "times-bold": "tibo",
    "courier": "cour",
    "courier-bold": "cobo",
}

DEFAULT_FONT = "helvetica"


def open_document(source: str | Path, password: str | None = None) -> pymupdf.Document:
    """Öffnet ein PDF mit PyMuPDF und entschlüsselt es bei Bedarf."""
    try:
        document = pymupdf.open(str(source))
    except Exception as exc:  # pymupdf wirft je nach Defekt sehr unterschiedliche Typen
        raise PdfToolError(f"{Path(source).name} lässt sich nicht öffnen: {exc}") from exc

    if document.needs_pass and not document.authenticate(password or ""):
        document.close()
        raise PasswordRequiredError(f"{Path(source).name} ist passwortgeschützt.")

    return document


def apply_annotations(
    source: str | Path,
    target: str | Path,
    annotations: list[dict],
    password: str | None = None,
) -> Path:
    """Zeichnet eine Liste von Elementen ins Dokument und speichert es.

    Unterstützte ``type``-Werte: ``text``, ``image``, ``rect``, ``ellipse``,
    ``line``, ``highlight``, ``redact``. Gemeinsame Felder sind ``page``
    (1-basiert) und die Anteile ``x``/``y`` (linke obere Ecke) sowie
    ``w``/``h`` bzw. ``x2``/``y2`` für Linien.
    """
    document = open_document(source, password)
    try:
        if not annotations:
            raise PdfToolError("Es wurde kein Element zum Einfügen übergeben.")

        pages_with_redactions: set[int] = set()

        for annotation in annotations:
            number = int(annotation.get("page", 1))
            if number < 1 or number > document.page_count:
                raise PdfToolError(
                    f"Seite {number} gibt es nicht (1-{document.page_count})."
                )

            page = document[number - 1]
            kind = str(annotation.get("type", "text")).lower()

            if kind == "text":
                _draw_text(page, annotation)
            elif kind == "image":
                _draw_image(page, annotation)
            elif kind in {"rect", "ellipse"}:
                _draw_shape(page, annotation, kind)
            elif kind == "line":
                _draw_line(page, annotation)
            elif kind == "highlight":
                _draw_highlight(page, annotation)
            elif kind == "redact":
                _add_redaction(page, annotation)
                pages_with_redactions.add(number - 1)
            else:
                raise PdfToolError(f"Unbekannter Elementtyp: {kind}")

        # Schwärzungen erst am Ende anwenden -- apply_redactions() entfernt den
        # Inhalt endgültig und würde vorher eingefügte Elemente mit treffen.
        for index in pages_with_redactions:
            document[index].apply_redactions()

        return _save(document, target)
    finally:
        document.close()


def add_watermark(
    source: str | Path,
    target: str | Path,
    text: str,
    password: str | None = None,
    font_size: int = 48,
    color: str = "#c8c8c8",
    opacity: float = 0.35,
    angle: int = 45,
    pages: list[int] | None = None,
) -> Path:
    """Legt einen diagonalen Schriftzug über die Seiten (Entwurf, Vertraulich, ...)."""
    if not text.strip():
        raise PdfToolError("Für ein Wasserzeichen wird ein Text gebraucht.")

    document = open_document(source, password)
    try:
        font = pymupdf.Font("helv")
        rgb = hex_to_rgb(color)
        targets = pages or range(1, document.page_count + 1)

        for number in targets:
            page = document[number - 1]
            rect = page.rect
            width = font.text_length(text, font_size)

            # Mitte der Seite als Drehpunkt, Text darum zentriert absetzen.
            pivot = pymupdf.Point(rect.width / 2, rect.height / 2)
            start = pymupdf.Point(pivot.x - width / 2, pivot.y + font_size * 0.35)

            writer = pymupdf.TextWriter(rect)
            writer.append(start, text, font=font, fontsize=font_size)
            writer.write_text(
                page,
                color=rgb,
                opacity=max(0.0, min(1.0, opacity)),
                morph=(pivot, pymupdf.Matrix(angle)),
            )

        return _save(document, target)
    finally:
        document.close()


def add_page_numbers(
    source: str | Path,
    target: str | Path,
    password: str | None = None,
    position: str = "bottom-center",
    font_size: int = 10,
    start_at: int = 1,
    template: str = "{page}",
) -> Path:
    """Nummeriert die Seiten. ``template`` kennt ``{page}`` und ``{total}``."""
    document = open_document(source, password)
    try:
        font = pymupdf.Font("helv")
        total = document.page_count

        for index, page in enumerate(document):
            label = template.format(page=index + start_at, total=total + start_at - 1)
            rect = page.rect
            width = font.text_length(label, font_size)
            margin = 28.0

            if position.endswith("left"):
                x = margin
            elif position.endswith("right"):
                x = rect.width - margin - width
            else:
                x = (rect.width - width) / 2

            y = margin if position.startswith("top") else rect.height - margin + font_size / 2

            writer = pymupdf.TextWriter(rect)
            writer.append(pymupdf.Point(x, y), label, font=font, fontsize=font_size)
            writer.write_text(page, color=(0, 0, 0))

        return _save(document, target)
    finally:
        document.close()


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """Wandelt "#ff8800" in die von PyMuPDF erwarteten Anteile 0.0-1.0."""
    text = (value or "#000000").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        raise PdfToolError(f"Unverständliche Farbe: {value!r}")
    try:
        return tuple(int(text[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise PdfToolError(f"Unverständliche Farbe: {value!r}") from exc


def _rect_from(page: pymupdf.Page, annotation: dict) -> pymupdf.Rect:
    """Rechnet Anteile in Punkte um -- ohne Rotation der Seite zu ignorieren."""
    bounds = page.rect
    x = float(annotation.get("x", 0)) * bounds.width
    y = float(annotation.get("y", 0)) * bounds.height
    width = float(annotation.get("w", 0.2)) * bounds.width
    height = float(annotation.get("h", 0.05)) * bounds.height

    rect = pymupdf.Rect(x, y, x + width, y + height)
    if page.rotation:
        rect *= page.derotation_matrix
    return rect


def _point_from(page: pymupdf.Page, annotation: dict, x_key: str, y_key: str) -> pymupdf.Point:
    bounds = page.rect
    point = pymupdf.Point(
        float(annotation.get(x_key, 0)) * bounds.width,
        float(annotation.get(y_key, 0)) * bounds.height,
    )
    if page.rotation:
        point *= page.derotation_matrix
    return point


def _draw_text(page: pymupdf.Page, annotation: dict) -> None:
    text = str(annotation.get("text", "")).strip()
    if not text:
        raise PdfToolError("Ein Textelement ohne Inhalt lässt sich nicht setzen.")

    font_size = float(annotation.get("size", 12))
    font_name = FONTS.get(str(annotation.get("font", DEFAULT_FONT)).lower(), "helv")
    color = hex_to_rgb(str(annotation.get("color", "#000000")))
    rect = _rect_from(page, annotation)

    # Der Kasten wächst nach unten, falls die Höhe zu knapp geraten ist:
    # insert_textbox meldet mit einem negativen Wert, dass der Text nicht passt.
    for attempt in range(4):
        overflow = page.insert_textbox(
            rect,
            text,
            fontsize=font_size,
            fontname=font_name,
            color=color,
            align=_align(annotation.get("align")),
            rotate=page.rotation or 0,
        )
        if overflow >= 0:
            return
        rect = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + abs(overflow) + font_size)
        if attempt == 3:
            raise PdfToolError("Der Text passt nicht auf die Seite.")


def _draw_image(page: pymupdf.Page, annotation: dict) -> None:
    source = annotation.get("image_path")
    if not source or not Path(source).is_file():
        raise PdfToolError("Die einzufügende Bilddatei wurde nicht gefunden.")

    try:
        page.insert_image(
            _rect_from(page, annotation),
            filename=str(source),
            keep_proportion=bool(annotation.get("keep_proportion", True)),
            overlay=True,
        )
    except Exception as exc:
        raise PdfToolError(f"Das Bild liess sich nicht einfügen: {exc}") from exc


def _draw_shape(page: pymupdf.Page, annotation: dict, kind: str) -> None:
    rect = _rect_from(page, annotation)
    shape = page.new_shape()

    if kind == "rect":
        shape.draw_rect(rect)
    else:
        shape.draw_oval(rect)

    stroke = annotation.get("color", "#d92d20")
    fill = annotation.get("fill")
    shape.finish(
        color=hex_to_rgb(str(stroke)) if stroke else None,
        fill=hex_to_rgb(str(fill)) if fill else None,
        width=float(annotation.get("width", 1.5)),
        fill_opacity=float(annotation.get("opacity", 1.0)),
        stroke_opacity=float(annotation.get("opacity", 1.0)),
    )
    shape.commit()


def _draw_line(page: pymupdf.Page, annotation: dict) -> None:
    shape = page.new_shape()
    shape.draw_line(
        _point_from(page, annotation, "x", "y"),
        _point_from(page, annotation, "x2", "y2"),
    )
    shape.finish(
        color=hex_to_rgb(str(annotation.get("color", "#d92d20"))),
        width=float(annotation.get("width", 1.5)),
    )
    shape.commit()


def _draw_highlight(page: pymupdf.Page, annotation: dict) -> None:
    highlight = page.add_highlight_annot(_rect_from(page, annotation))
    highlight.set_colors(stroke=hex_to_rgb(str(annotation.get("color", "#ffe14d"))))
    highlight.update()


def _add_redaction(page: pymupdf.Page, annotation: dict) -> None:
    """Merkt eine Schwärzung vor. Angewendet wird sie erst am Ende -- siehe apply_annotations."""
    page.add_redact_annot(
        _rect_from(page, annotation),
        fill=hex_to_rgb(str(annotation.get("color", "#000000"))),
    )


def _align(value) -> int:
    return {"left": 0, "center": 1, "right": 2, "justify": 3}.get(str(value or "left").lower(), 0)


def _save(document: pymupdf.Document, target: str | Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # garbage/deflate hält die Datei nach mehreren Bearbeitungsrunden klein.
    document.save(str(target), garbage=3, deflate=True)
    return target
