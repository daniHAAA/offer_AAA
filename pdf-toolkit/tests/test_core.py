"""Die eigentlichen Werkzeuge -- geprüft wird immer am Ergebnisdokument."""

from pathlib import Path

import pytest

from conftest import build_pdf
from pdftoolkit.core import convert, edit, forms, merge, organize, security, split
from pdftoolkit.core.document import PasswordRequiredError, PdfToolError, describe


# ------------------------------------------------------------ zusammenfügen

def test_merge_keeps_order_and_count(sample, other, workdir):
    result = merge.merge_pdfs([sample, other], workdir / "out.pdf")
    assert describe(result).page_count == 5
    assert "Sample Seite 1" in convert.pdf_to_text(result, selection="1")
    assert "Other Seite 1" in convert.pdf_to_text(result, selection="4")


def test_merge_with_selection_per_file(sample, other, workdir):
    result = merge.merge_pdfs([sample, other], workdir / "out.pdf", selections=["2", "1-2"])
    assert describe(result).page_count == 3
    assert "Sample Seite 2" in convert.pdf_to_text(result, selection="1")


def test_merge_needs_at_least_one_source(workdir):
    with pytest.raises(PdfToolError):
        merge.merge_pdfs([], workdir / "out.pdf")


# ------------------------------------------------------------ teilen

def test_split_by_ranges(sample, workdir):
    parts = split.split_by_ranges(sample, workdir / "parts", ["1-2", "3"])
    assert [describe(part).page_count for part in parts] == [2, 1]


def test_split_every_page(sample, workdir):
    parts = split.split_every_page(sample, workdir / "single")
    assert len(parts) == 3
    assert all(describe(part).page_count == 1 for part in parts)


def test_split_into_chunks_handles_remainder(workdir):
    source = build_pdf(workdir / "long.pdf", 7)
    parts = split.split_into_chunks(source, workdir / "chunks", 3)
    assert [describe(part).page_count for part in parts] == [3, 3, 1]


def test_extract_pages(sample, workdir):
    result = split.extract_pages(sample, workdir / "extract.pdf", "3,1")
    assert describe(result).page_count == 2
    assert "Sample Seite 3" in convert.pdf_to_text(result, selection="1")


def test_split_rejects_empty_ranges(sample, workdir):
    with pytest.raises(PdfToolError):
        split.split_by_ranges(sample, workdir / "x", [])


# ------------------------------------------------------------ organisieren

def test_apply_layout_reorders_and_rotates(sample, workdir):
    result = organize.apply_layout(
        sample, workdir / "org.pdf", [{"page": 3, "rotate": 90}, {"page": 1}]
    )
    info = describe(result)
    assert info.page_count == 2
    assert info.pages[0].rotation == 90
    assert "Sample Seite 3" in convert.pdf_to_text(result, selection="1")


def test_delete_pages(sample, workdir):
    result = organize.delete_pages(sample, workdir / "del.pdf", "2")
    assert describe(result).page_count == 2
    assert "Seite 2" not in convert.pdf_to_text(result)


def test_delete_all_pages_is_refused(sample, workdir):
    with pytest.raises(PdfToolError):
        organize.delete_pages(sample, workdir / "del.pdf", "1-3")


def test_rotate_only_selected_pages(sample, workdir):
    result = organize.rotate_pages(sample, workdir / "rot.pdf", "2", 180)
    assert [page.rotation for page in describe(result).pages] == [0, 180, 0]


def test_layout_rejects_unknown_page(sample, workdir):
    with pytest.raises(PdfToolError):
        organize.apply_layout(sample, workdir / "x.pdf", [{"page": 99}])


def test_layout_rejects_odd_angle(sample, workdir):
    with pytest.raises(PdfToolError):
        organize.apply_layout(sample, workdir / "x.pdf", [{"page": 1, "rotate": 45}])


def test_insert_pdf_at_position(sample, other, workdir):
    result = organize.insert_pdf(sample, other, workdir / "ins.pdf", after_page=1)
    assert describe(result).page_count == 5
    assert "Other Seite 1" in convert.pdf_to_text(result, selection="2")


# ------------------------------------------------------------ bearbeiten

def test_add_text_appears_in_document(sample, workdir):
    result = edit.apply_annotations(sample, workdir / "edit.pdf", [
        {"type": "text", "page": 1, "x": .1, "y": .5, "w": .7, "h": .1, "text": "Grüezi Daniel"},
    ])
    assert "Grüezi Daniel" in convert.pdf_to_text(result, selection="1")


def test_redaction_really_removes_text(sample, workdir):
    """Eine Schwärzung muss den Text entfernen, nicht nur überdecken."""
    result = edit.apply_annotations(sample, workdir / "red.pdf", [
        {"type": "redact", "page": 1, "x": .0, "y": .05, "w": 1.0, "h": .2},
    ])
    assert "Sample Seite 1" not in convert.pdf_to_text(result, selection="1")
    assert "Sample Seite 2" in convert.pdf_to_text(result, selection="2")


def test_shapes_and_image(sample, image_file, workdir):
    result = edit.apply_annotations(sample, workdir / "shapes.pdf", [
        {"type": "rect", "page": 1, "x": .1, "y": .1, "w": .3, "h": .1},
        {"type": "ellipse", "page": 1, "x": .5, "y": .1, "w": .2, "h": .1, "fill": "#ffe14d"},
        {"type": "line", "page": 2, "x": .1, "y": .2, "x2": .8, "y2": .4},
        {"type": "highlight", "page": 2, "x": .1, "y": .12, "w": .5, "h": .03},
        {"type": "image", "page": 3, "x": .2, "y": .2, "w": .3, "h": .2,
         "image_path": str(image_file)},
    ])
    assert describe(result).page_count == 3


def test_edit_rejects_unknown_type(sample, workdir):
    with pytest.raises(PdfToolError):
        edit.apply_annotations(sample, workdir / "x.pdf", [{"type": "zauberstab", "page": 1}])


def test_edit_rejects_missing_image(sample, workdir):
    with pytest.raises(PdfToolError):
        edit.apply_annotations(sample, workdir / "x.pdf", [
            {"type": "image", "page": 1, "image_path": "/gibt/es/nicht.png"},
        ])


def test_watermark_on_every_page(sample, workdir):
    result = edit.add_watermark(sample, workdir / "wm.pdf", "ENTWURF")
    text = convert.pdf_to_text(result)
    assert text.count("ENTWURF") == 3


def test_page_numbers_use_template(sample, workdir):
    result = edit.add_page_numbers(sample, workdir / "num.pdf", template="Seite {page} von {total}")
    assert "Seite 2 von 3" in convert.pdf_to_text(result, selection="2")


def test_hex_to_rgb():
    assert edit.hex_to_rgb("#ffffff") == (1.0, 1.0, 1.0)
    assert edit.hex_to_rgb("#000") == (0.0, 0.0, 0.0)
    with pytest.raises(PdfToolError):
        edit.hex_to_rgb("blau")


# ------------------------------------------------------------ formulare

def test_read_fields(form_pdf):
    fields = {field["name"]: field for field in forms.read_fields(form_pdf)}
    assert set(fields) == {"name", "agb", "stufe"}
    assert fields["agb"]["type"] == "CheckBox"
    assert fields["stufe"]["options"] == ["Anfänger", "Profi"]
    assert 0 <= fields["name"]["rect"]["x"] <= 1


def test_fill_and_read_back(form_pdf, workdir):
    result = forms.fill_fields(form_pdf, workdir / "filled.pdf",
                               {"name": "Daniel", "agb": True, "stufe": "Profi"})
    values = forms.export_values(result)
    assert values["name"] == "Daniel"
    assert values["agb"] is True
    assert values["stufe"] == "Profi"


def test_flatten_removes_fields_but_keeps_text(form_pdf, workdir):
    result = forms.fill_fields(form_pdf, workdir / "flat.pdf",
                               {"name": "Daniel", "agb": True}, flatten=True)
    assert forms.read_fields(result) == []
    text = convert.pdf_to_text(result)
    assert "Daniel" in text
    assert "X" in text


def test_fill_rejects_unknown_field(form_pdf, workdir):
    with pytest.raises(PdfToolError, match="Unbekannte Felder"):
        forms.fill_fields(form_pdf, workdir / "x.pdf", {"telefon": "123"})


def test_fill_rejects_invalid_option(form_pdf, workdir):
    with pytest.raises(PdfToolError, match="erlaubt nur"):
        forms.fill_fields(form_pdf, workdir / "x.pdf", {"stufe": "Weltmeister"})


def test_fill_on_document_without_form(sample, workdir):
    with pytest.raises(PdfToolError, match="keine Formularfelder"):
        forms.fill_fields(sample, workdir / "x.pdf", {"name": "Daniel"})


# ------------------------------------------------------------ umwandeln

def test_pdf_to_text_selection(sample):
    assert "Sample Seite 2" in convert.pdf_to_text(sample, selection="2")
    assert "Sample Seite 1" not in convert.pdf_to_text(sample, selection="2")


def test_pdf_to_images(sample, workdir):
    files = convert.pdf_to_images(sample, workdir / "img", dpi=72, selection="1-2")
    assert len(files) == 2
    assert all(path.stat().st_size > 0 for path in files)


def test_pdf_to_images_rejects_absurd_dpi(sample, workdir):
    with pytest.raises(PdfToolError):
        convert.pdf_to_images(sample, workdir / "img", dpi=5000)


def test_images_to_pdf(image_file, workdir):
    result = convert.images_to_pdf([image_file, image_file], workdir / "img.pdf")
    assert describe(result).page_count == 2


def test_pdf_to_word(sample, workdir):
    pytest.importorskip("pdf2docx")
    result = convert.pdf_to_word(sample, workdir / "out.docx")
    assert result.is_file() and result.stat().st_size > 0


# ------------------------------------------------------------ schutz

def test_encrypt_then_open_needs_password(sample, workdir):
    encrypted = security.encrypt(sample, workdir / "enc.pdf", "geheim")
    with pytest.raises(PasswordRequiredError):
        describe(encrypted)
    assert describe(encrypted, "geheim").page_count == 3


def test_decrypt_restores_open_access(sample, workdir):
    encrypted = security.encrypt(sample, workdir / "enc.pdf", "geheim")
    opened = security.decrypt(encrypted, workdir / "dec.pdf", "geheim")
    assert describe(opened).page_count == 3


def test_encrypt_requires_password(sample, workdir):
    with pytest.raises(PdfToolError):
        security.encrypt(sample, workdir / "x.pdf", "")


def test_compress_reports_sizes(sample, workdir):
    stats = security.compress(sample, workdir / "small.pdf")
    assert stats["after"] > 0
    assert stats["before"] >= stats["after"]
    assert (workdir / "small.pdf").is_file()


# ------------------------------------------------------------ fehlerfälle

def test_missing_file(workdir):
    with pytest.raises(PdfToolError, match="nicht gefunden"):
        describe(workdir / "gibtsnicht.pdf")


def test_broken_file(workdir):
    broken = workdir / "kaputt.pdf"
    broken.write_bytes(b"das ist kein PDF")
    with pytest.raises(PdfToolError):
        describe(broken)
