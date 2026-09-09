"""Kommandozeile -- geprüft über den Rückgabewert und das erzeugte Ergebnis."""

import json

import pytest

from conftest import build_form, build_image, build_pdf
from pdftoolkit.cli import main
from pdftoolkit.core import convert, forms
from pdftoolkit.core.document import describe


def run(*args) -> int:
    return main([str(arg) for arg in args])


def test_info(capsys, sample):
    assert run("info", sample) == 0
    assert "Seiten     : 3" in capsys.readouterr().out


def test_info_json(capsys, sample):
    assert run("info", sample, "--json") == 0
    assert json.loads(capsys.readouterr().out)["page_count"] == 3


def test_merge(sample, other, workdir):
    assert run("merge", sample, other, "-o", workdir / "out.pdf") == 0
    assert describe(workdir / "out.pdf").page_count == 5


def test_merge_with_page_selection(sample, other, workdir):
    assert run("merge", sample, other, "-o", workdir / "out.pdf", "--pages", "1", "2") == 0
    assert describe(workdir / "out.pdf").page_count == 2


def test_split_ranges(capsys, sample, workdir):
    assert run("split", sample, "-o", workdir / "parts", "--ranges", "1-2", "3") == 0
    assert "2 Dateien erstellt." in capsys.readouterr().out


def test_split_every_page(sample, workdir):
    assert run("split", sample, "-o", workdir / "single", "--every-page") == 0
    assert len(list((workdir / "single").glob("*.pdf"))) == 3


def test_extract(sample, workdir):
    assert run("extract", sample, "-o", workdir / "aus.pdf", "--pages", "2,3") == 0
    assert describe(workdir / "aus.pdf").page_count == 2


def test_organize_delete_and_order(sample, workdir):
    target = workdir / "org.pdf"
    assert run("organize", sample, "-o", target, "--delete", "2", "--order", "2,1") == 0
    assert describe(target).page_count == 2
    assert "Sample Seite 3" in convert.pdf_to_text(target, selection="1")
    assert not list(workdir.glob("*.tmp-*.pdf"))  # Zwischendateien sind weg


def test_organize_rotate(sample, workdir):
    target = workdir / "rot.pdf"
    assert run("organize", sample, "-o", target, "--rotate", "1", "--degrees", "180") == 0
    assert [page.rotation for page in describe(target).pages] == [180, 0, 0]


def test_organize_needs_an_action(sample, workdir):
    assert run("organize", sample, "-o", workdir / "x.pdf") == 1


def test_insert(sample, other, workdir):
    assert run("insert", sample, other, "-o", workdir / "ins.pdf", "--after", "1") == 0
    assert describe(workdir / "ins.pdf").page_count == 5


def test_watermark(sample, workdir):
    assert run("watermark", sample, "-o", workdir / "wm.pdf", "--text", "ENTWURF") == 0
    assert "ENTWURF" in convert.pdf_to_text(workdir / "wm.pdf")


def test_page_numbers(sample, workdir):
    assert run("numbers", sample, "-o", workdir / "num.pdf",
               "--template", "Seite {page} von {total}") == 0
    assert "Seite 3 von 3" in convert.pdf_to_text(workdir / "num.pdf", selection="3")


def test_edit_from_json(sample, workdir):
    plan = workdir / "plan.json"
    plan.write_text(json.dumps([
        {"type": "text", "page": 1, "x": .1, "y": .5, "w": .6, "h": .1, "text": "Aus JSON"},
    ]), encoding="utf-8")

    assert run("edit", sample, "-o", workdir / "edit.pdf", "--annotations", plan) == 0
    assert "Aus JSON" in convert.pdf_to_text(workdir / "edit.pdf", selection="1")


def test_text_to_stdout(capsys, sample):
    assert run("text", sample) == 0
    assert "Sample Seite 1" in capsys.readouterr().out


def test_images(sample, workdir):
    assert run("images", sample, "-o", workdir / "img", "--dpi", "72") == 0
    assert len(list((workdir / "img").glob("*.png"))) == 3


def test_from_images(image_file, workdir):
    assert run("from-images", image_file, image_file, "-o", workdir / "bilder.pdf") == 0
    assert describe(workdir / "bilder.pdf").page_count == 2


def test_word(sample, workdir):
    pytest.importorskip("pdf2docx")
    assert run("word", sample, "-o", workdir / "out.docx") == 0
    assert (workdir / "out.docx").stat().st_size > 0


def test_form_list(capsys, form_pdf):
    assert run("form", "list", form_pdf) == 0
    output = capsys.readouterr().out
    assert "name" in output and "CheckBox" in output


def test_form_fill_with_set(form_pdf, workdir):
    target = workdir / "fertig.pdf"
    assert run("form", "fill", form_pdf, "-o", target,
               "--set", "name=Daniel", "--set", "agb=true") == 0
    values = forms.export_values(target)
    assert values["name"] == "Daniel"
    assert values["agb"] is True


def test_form_fill_from_json(form_pdf, workdir):
    values_file = workdir / "werte.json"
    values_file.write_text(json.dumps({"name": "Aus Datei"}), encoding="utf-8")
    target = workdir / "fertig.pdf"

    assert run("form", "fill", form_pdf, "-o", target, "--values", values_file) == 0
    assert forms.export_values(target)["name"] == "Aus Datei"


def test_form_fill_rejects_bad_pair(capsys, form_pdf, workdir):
    assert run("form", "fill", form_pdf, "-o", workdir / "x.pdf", "--set", "kaputt") == 1
    assert "FELD=WERT" in capsys.readouterr().err


def test_form_flatten(form_pdf, workdir):
    assert run("form", "flatten", form_pdf, "-o", workdir / "flach.pdf") == 0
    assert forms.read_fields(workdir / "flach.pdf") == []


def test_encrypt_and_decrypt(sample, workdir):
    protected = workdir / "enc.pdf"
    assert run("encrypt", sample, "-o", protected, "--set-password", "geheim") == 0
    assert describe(protected, "geheim").page_count == 3

    assert run("decrypt", protected, "-o", workdir / "dec.pdf", "--password", "geheim") == 0
    assert describe(workdir / "dec.pdf").page_count == 3


def test_compress(capsys, sample, workdir):
    assert run("compress", sample, "-o", workdir / "klein.pdf") == 0
    assert "kleiner" in capsys.readouterr().out


def test_in_place_write_is_refused(capsys, sample):
    """Quelle == Ziel würde die Vorlage zerstören und muss abgelehnt werden."""
    assert run("extract", sample, "-o", sample, "--pages", "1") == 1
    assert "dieselbe Datei" in capsys.readouterr().err
    assert describe(sample).page_count == 3  # unverändert


def test_missing_file_reports_error(capsys, workdir):
    assert run("info", workdir / "gibtsnicht.pdf") == 1
    assert "Fehler" in capsys.readouterr().err
