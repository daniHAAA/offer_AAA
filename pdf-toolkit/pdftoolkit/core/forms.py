"""PDF-Formulare: Felder auslesen, ausfüllen und fest ins Dokument einbrennen.

Hier wird durchgehend PyMuPDF benutzt. Es liefert Feldname, Typ, Wert und
die Position auf der Seite in einem Rutsch -- genau das, was die Oberfläche
braucht, um ein Formular als Liste darstellen zu können.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .document import PdfToolError
from .edit import _save, open_document

# Feldtypen, bei denen ein Häkchen statt eines Textes erwartet wird.
BOOLEAN_TYPES = {"CheckBox"}
CHOICE_TYPES = {"ComboBox", "ListBox", "RadioButton"}


def read_fields(source: str | Path, password: str | None = None) -> list[dict]:
    """Listet alle Formularfelder mit Typ, aktuellem Wert und Position."""
    document = open_document(source, password)
    try:
        fields: list[dict] = []
        for index, page in enumerate(document, start=1):
            for widget in page.widgets():
                bounds = page.rect
                rect = widget.rect
                fields.append(
                    {
                        "name": widget.field_name or "",
                        "label": widget.field_label or widget.field_name or "",
                        "type": widget.field_type_string,
                        "value": _readable_value(widget),
                        "options": list(widget.choice_values or []),
                        "readonly": bool(widget.field_flags & 1),
                        "required": bool(widget.field_flags & 2),
                        "page": index,
                        # Anteile statt Punkte: die Oberfläche kann das Feld so
                        # direkt über der Seitenvorschau einblenden.
                        "rect": {
                            "x": round(rect.x0 / bounds.width, 5),
                            "y": round(rect.y0 / bounds.height, 5),
                            "w": round(rect.width / bounds.width, 5),
                            "h": round(rect.height / bounds.height, 5),
                        },
                    }
                )
        return fields
    finally:
        document.close()


def fill_fields(
    source: str | Path,
    target: str | Path,
    values: dict[str, object],
    password: str | None = None,
    flatten: bool = False,
) -> Path:
    """Trägt Werte in die Felder ein.

    Mit ``flatten=True`` werden die Werte fest in die Seite gezeichnet und die
    Felder entfernt -- das Ergebnis ist nicht mehr veränderbar und sieht in
    jedem Betrachter gleich aus.
    """
    document = open_document(source, password)
    try:
        known = {
            widget.field_name
            for page in document
            for widget in page.widgets()
            if widget.field_name
        }
        if not known:
            raise PdfToolError("Dieses PDF enthält keine Formularfelder.")

        unknown = set(values) - known
        if unknown:
            raise PdfToolError("Unbekannte Felder: " + ", ".join(sorted(unknown)))

        for page in document:
            for widget in page.widgets():
                if widget.field_name not in values:
                    continue
                _assign(widget, values[widget.field_name])
                widget.update()

        if flatten:
            _flatten(document)

        return _save(document, target)
    finally:
        document.close()


def flatten_form(source: str | Path, target: str | Path, password: str | None = None) -> Path:
    """Brennt ein bereits ausgefülltes Formular fest ein, ohne Werte zu ändern."""
    document = open_document(source, password)
    try:
        _flatten(document)
        return _save(document, target)
    finally:
        document.close()


def export_values(source: str | Path, password: str | None = None) -> dict[str, object]:
    """Gibt nur die Feldwerte zurück -- praktisch, um sie in ein anderes Formular zu übernehmen."""
    return {field["name"]: field["value"] for field in read_fields(source, password) if field["name"]}


def _assign(widget: pymupdf.Widget, value: object) -> None:
    """Setzt einen Wert typgerecht -- ein Häkchen ist etwas anderes als ein Text."""
    kind = widget.field_type_string

    if kind in BOOLEAN_TYPES:
        widget.field_value = _as_bool(value)
        return

    text = "" if value is None else str(value)

    if kind in CHOICE_TYPES and widget.choice_values:
        allowed = {str(option): str(option) for option in widget.choice_values}
        # Auswahllisten können Paare (Exportwert, Anzeigetext) enthalten.
        for option in widget.choice_values:
            if isinstance(option, (list, tuple)) and option:
                allowed[str(option[0])] = str(option[0])
                if len(option) > 1:
                    allowed[str(option[1])] = str(option[0])
        if text and text not in allowed:
            raise PdfToolError(
                f"{widget.field_name!r} erlaubt nur: " + ", ".join(sorted(set(allowed)))
            )
        widget.field_value = allowed.get(text, text)
        return

    widget.field_value = text


def _flatten(document: pymupdf.Document) -> None:
    """Zeichnet Feldwerte als normalen Inhalt und entfernt danach die Felder."""
    font = pymupdf.Font("helv")

    for page in document:
        widgets = list(page.widgets())
        for widget in widgets:
            text = _readable_value(widget)
            display = _display_text(widget, text)

            if display:
                rect = widget.rect
                size = min(float(widget.text_fontsize or 0) or 10.0, max(rect.height - 2, 4))
                writer = pymupdf.TextWriter(page.rect)
                writer.append(
                    pymupdf.Point(rect.x0 + 2, rect.y1 - (rect.height - size) / 2 - size * 0.22),
                    display,
                    font=font,
                    fontsize=size,
                )
                writer.write_text(page, color=(0, 0, 0))

            page.delete_widget(widget)


def _display_text(widget: pymupdf.Widget, value: object) -> str:
    if widget.field_type_string in BOOLEAN_TYPES:
        return "X" if value else ""
    return "" if value is None else str(value)


def _readable_value(widget: pymupdf.Widget) -> object:
    if widget.field_type_string in BOOLEAN_TYPES:
        return _as_bool(widget.field_value)
    return widget.field_value if widget.field_value is not None else ""


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "ja", "on", "x", "checked"}
