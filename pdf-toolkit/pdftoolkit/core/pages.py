"""Seitenauswahl: übersetzt Nutzereingaben wie "1-3,5,8-" in Seitenindizes.

Nach aussen wird immer 1-basiert gezählt (wie im PDF-Viewer), intern
0-basiert (wie in pypdf/PyMuPDF). Diese Umrechnung passiert genau hier,
damit sie nicht in jedem Werkzeug erneut auftaucht.
"""

from __future__ import annotations

import re

_RANGE_RE = re.compile(r"^\s*(\d*)\s*-\s*(\d*)\s*$")


class PageSelectionError(ValueError):
    """Die Seitenangabe konnte nicht gelesen oder nicht angewendet werden."""


def parse_page_selection(expression: str | None, page_count: int) -> list[int]:
    """Wandelt eine Seitenangabe in eine Liste 0-basierter Indizes.

    Erlaubt sind Einzelseiten (``4``), Bereiche (``2-6``), offene Bereiche
    (``-3`` = ab Anfang, ``7-`` = bis Ende), ``all`` sowie Kombinationen mit
    Komma. Die Reihenfolge der Eingabe bleibt erhalten, Duplikate werden
    entfernt -- so lässt sich derselbe Parser auch zum Umsortieren nutzen.
    """
    if page_count <= 0:
        raise PageSelectionError("Das Dokument enthält keine Seiten.")

    text = (expression or "").strip()
    if not text or text.lower() in {"all", "alle", "*"}:
        return list(range(page_count))

    indices: list[int] = []
    seen: set[int] = set()

    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue

        match = _RANGE_RE.match(part)
        if match:
            start_text, end_text = match.groups()
            start = _to_index(start_text, page_count, default=1)
            end = _to_index(end_text, page_count, default=page_count)
            step = 1 if end >= start else -1
            candidates = range(start, end + step, step)
        elif part.isdigit():
            candidates = [_to_index(part, page_count, default=None)]
        else:
            raise PageSelectionError(f"Unverständliche Seitenangabe: {part!r}")

        for index in candidates:
            if index not in seen:
                seen.add(index)
                indices.append(index)

    if not indices:
        raise PageSelectionError(f"Die Angabe {text!r} ergibt keine Seiten.")
    return indices


def _to_index(text: str, page_count: int, default: int | None) -> int:
    """Macht aus einer 1-basierten Seitennummer einen geprüften 0-basierten Index."""
    if not text:
        if default is None:
            raise PageSelectionError("Es fehlt eine Seitennummer.")
        number = default
    else:
        number = int(text)

    if number < 1 or number > page_count:
        raise PageSelectionError(
            f"Seite {number} liegt ausserhalb des Dokuments (1-{page_count})."
        )
    return number - 1


def format_page_selection(indices: list[int]) -> str:
    """Fasst 0-basierte Indizes wieder zu einer lesbaren Angabe zusammen ("1-3,7")."""
    if not indices:
        return ""

    parts: list[str] = []
    start = previous = indices[0]

    for index in indices[1:]:
        if index == previous + 1:
            previous = index
            continue
        parts.append(_format_run(start, previous))
        start = previous = index

    parts.append(_format_run(start, previous))
    return ",".join(parts)


def _format_run(start: int, end: int) -> str:
    if start == end:
        return str(start + 1)
    return f"{start + 1}-{end + 1}"
