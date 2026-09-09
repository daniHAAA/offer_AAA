"""Gemeinsame Testbausteine: erzeugt PDFs, statt welche mitzuliefern."""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_pdf(path: Path, page_count: int = 3, label: str = "Dokument") -> Path:
    """Legt ein PDF mit erkennbarem Text auf jeder Seite an."""
    document = pymupdf.open()
    for number in range(1, page_count + 1):
        page = document.new_page()
        page.insert_text((72, 100), f"{label} Seite {number}", fontsize=18)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    document.close()
    return path


def build_form(path: Path) -> Path:
    """Legt ein PDF mit Text-, Auswahl- und Ankreuzfeld an."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "Anmeldung", fontsize=16)

    definitions = [
        (pymupdf.PDF_WIDGET_TYPE_TEXT, "name", (72, 120, 320, 145), {}),
        (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "agb", (72, 160, 90, 178), {}),
        (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "stufe", (72, 200, 320, 225),
         {"choice_values": ["Anfänger", "Profi"]}),
    ]
    for field_type, name, rect, extra in definitions:
        widget = pymupdf.Widget()
        widget.field_type = field_type
        widget.field_name = name
        widget.rect = pymupdf.Rect(*rect)
        for key, value in extra.items():
            setattr(widget, key, value)
        page.add_widget(widget)

    document.save(str(path))
    document.close()
    return path


def build_image(path: Path, size: tuple[int, int] = (200, 120)) -> Path:
    """Legt ein einfarbiges PNG an."""
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, *size), False)
    pixmap.set_rect(pixmap.irect, (40, 90, 200))
    pixmap.save(str(path))
    return path


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    return build_pdf(tmp_path / "sample.pdf", 3, "Sample")


@pytest.fixture
def other(tmp_path: Path) -> Path:
    return build_pdf(tmp_path / "other.pdf", 2, "Other")


@pytest.fixture
def form_pdf(tmp_path: Path) -> Path:
    return build_form(tmp_path / "form.pdf")


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    return build_image(tmp_path / "bild.png")
