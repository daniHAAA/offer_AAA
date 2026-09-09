"""Kommandozeile des Toolkits.

Dieselbe Fachlogik wie die Weboberfläche, nur ohne Browser -- gedacht für
Stapelverarbeitung ("alle Rechnungen des Monats zusammenfügen") und für
Skripte.

    python -m pdftoolkit.cli --help
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import convert, edit, forms, merge, organize, security, split
from .core.document import PdfToolError, describe
from .core.pages import PageSelectionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdftoolkit",
        description="PDF-Werkzeugkasten: zusammenfügen, teilen, organisieren, "
                    "bearbeiten, umwandeln, Formulare, Schutz.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            "  pdftoolkit merge a.pdf b.pdf -o zusammen.pdf\n"
            "  pdftoolkit split bericht.pdf -o teile/ --ranges 1-3 4-\n"
            "  pdftoolkit organize scan.pdf -o final.pdf --delete 2,5 --rotate 1-3 --degrees 90\n"
            "  pdftoolkit watermark angebot.pdf -o entwurf.pdf --text ENTWURF\n"
            "  pdftoolkit word bericht.pdf -o bericht.docx\n"
            "  pdftoolkit form fill formular.pdf -o fertig.pdf --set name=Daniel --set agb=true --flatten\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"pdftoolkit {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_password(target: argparse.ArgumentParser) -> None:
        target.add_argument("--password", help="Passwort, falls das PDF geschützt ist")

    # -- serve ---------------------------------------------------------
    serve = subparsers.add_parser("serve", help="Weboberfläche starten")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--no-browser", action="store_true", help="Browser nicht öffnen")

    # -- info ----------------------------------------------------------
    info = subparsers.add_parser("info", help="Eckdaten eines PDFs anzeigen")
    info.add_argument("source", type=Path)
    info.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    add_password(info)

    # -- merge ---------------------------------------------------------
    merge_cmd = subparsers.add_parser("merge", help="mehrere PDFs aneinanderhängen")
    merge_cmd.add_argument("sources", nargs="+", type=Path)
    merge_cmd.add_argument("-o", "--output", required=True, type=Path)
    merge_cmd.add_argument("--pages", nargs="*", default=None,
                           help="Seitenauswahl je Quelldatei, in gleicher Reihenfolge")
    merge_cmd.add_argument("--no-bookmarks", action="store_true")
    add_password(merge_cmd)

    # -- split ---------------------------------------------------------
    split_cmd = subparsers.add_parser("split", help="ein PDF in mehrere Dateien zerlegen")
    split_cmd.add_argument("source", type=Path)
    split_cmd.add_argument("-o", "--output", required=True, type=Path, help="Zielordner")
    group = split_cmd.add_mutually_exclusive_group(required=True)
    group.add_argument("--ranges", nargs="+", help="je Bereich eine Datei, z. B. 1-3 4-")
    group.add_argument("--every-page", action="store_true", help="jede Seite einzeln")
    group.add_argument("--chunks", type=int, metavar="N", help="alle N Seiten eine Datei")
    add_password(split_cmd)

    # -- extract -------------------------------------------------------
    extract = subparsers.add_parser("extract", help="Seiten in eine neue Datei ziehen")
    extract.add_argument("source", type=Path)
    extract.add_argument("-o", "--output", required=True, type=Path)
    extract.add_argument("--pages", required=True, help="z. B. 2,5,9-12")
    add_password(extract)

    # -- organize ------------------------------------------------------
    organize_cmd = subparsers.add_parser("organize", help="Seiten löschen, drehen, umsortieren")
    organize_cmd.add_argument("source", type=Path)
    organize_cmd.add_argument("-o", "--output", required=True, type=Path)
    organize_cmd.add_argument("--delete", help="Seiten entfernen, z. B. 2,5")
    organize_cmd.add_argument("--rotate", help="Seiten drehen, z. B. 1-3")
    organize_cmd.add_argument("--degrees", type=int, default=90, help="Drehwinkel (Standard 90)")
    organize_cmd.add_argument("--order", help="neue Reihenfolge, z. B. 3,1,2")
    add_password(organize_cmd)

    # -- insert --------------------------------------------------------
    insert = subparsers.add_parser("insert", help="ein PDF in ein anderes einfügen")
    insert.add_argument("source", type=Path)
    insert.add_argument("addition", type=Path)
    insert.add_argument("-o", "--output", required=True, type=Path)
    insert.add_argument("--after", type=int, default=0, help="hinter welcher Seite (0 = Anfang)")
    add_password(insert)

    # -- watermark / numbers -------------------------------------------
    watermark = subparsers.add_parser("watermark", help="Wasserzeichen über alle Seiten legen")
    watermark.add_argument("source", type=Path)
    watermark.add_argument("-o", "--output", required=True, type=Path)
    watermark.add_argument("--text", required=True)
    watermark.add_argument("--size", type=int, default=48)
    watermark.add_argument("--color", default="#c8c8c8")
    watermark.add_argument("--opacity", type=float, default=0.35)
    watermark.add_argument("--angle", type=int, default=45)
    add_password(watermark)

    numbers = subparsers.add_parser("numbers", help="Seitenzahlen einfügen")
    numbers.add_argument("source", type=Path)
    numbers.add_argument("-o", "--output", required=True, type=Path)
    numbers.add_argument("--position", default="bottom-center",
                         choices=["bottom-center", "bottom-left", "bottom-right",
                                  "top-center", "top-left", "top-right"])
    numbers.add_argument("--template", default="{page}", help="z. B. 'Seite {page} von {total}'")
    numbers.add_argument("--start-at", type=int, default=1)
    numbers.add_argument("--size", type=int, default=10)
    add_password(numbers)

    # -- edit ----------------------------------------------------------
    edit_cmd = subparsers.add_parser(
        "edit", help="Elemente aus einer JSON-Datei einfügen (Text, Formen, Schwärzung)")
    edit_cmd.add_argument("source", type=Path)
    edit_cmd.add_argument("-o", "--output", required=True, type=Path)
    edit_cmd.add_argument("--annotations", required=True, type=Path,
                          help="JSON-Liste, siehe README")
    add_password(edit_cmd)

    # -- convert -------------------------------------------------------
    word = subparsers.add_parser("word", help="PDF in eine Word-Datei umwandeln")
    word.add_argument("source", type=Path)
    word.add_argument("-o", "--output", required=True, type=Path)
    word.add_argument("--pages")
    add_password(word)

    text = subparsers.add_parser("text", help="Text aus einem PDF ziehen")
    text.add_argument("source", type=Path)
    text.add_argument("-o", "--output", type=Path, help="ohne Angabe: Ausgabe im Terminal")
    text.add_argument("--pages")
    text.add_argument("--layout", action="store_true", help="Anordnung grob erhalten")
    add_password(text)

    images = subparsers.add_parser("images", help="Seiten als Bilder speichern")
    images.add_argument("source", type=Path)
    images.add_argument("-o", "--output", required=True, type=Path, help="Zielordner")
    images.add_argument("--pages")
    images.add_argument("--dpi", type=int, default=150)
    images.add_argument("--format", default="png", choices=["png", "jpg"])
    add_password(images)

    from_images = subparsers.add_parser("from-images", help="Bilder zu einem PDF bündeln")
    from_images.add_argument("sources", nargs="+", type=Path)
    from_images.add_argument("-o", "--output", required=True, type=Path)

    # -- forms ---------------------------------------------------------
    form_cmd = subparsers.add_parser("form", help="Formularfelder lesen, ausfüllen, fixieren")
    form_sub = form_cmd.add_subparsers(dest="form_command", required=True)

    form_list = form_sub.add_parser("list", help="Felder anzeigen")
    form_list.add_argument("source", type=Path)
    form_list.add_argument("--json", action="store_true")
    add_password(form_list)

    form_fill = form_sub.add_parser("fill", help="Felder ausfüllen")
    form_fill.add_argument("source", type=Path)
    form_fill.add_argument("-o", "--output", required=True, type=Path)
    form_fill.add_argument("--set", action="append", default=[], metavar="FELD=WERT",
                           help="mehrfach verwendbar")
    form_fill.add_argument("--values", type=Path, help="JSON-Datei mit Feld/Wert-Paaren")
    form_fill.add_argument("--flatten", action="store_true", help="Werte fest einbrennen")
    add_password(form_fill)

    form_flatten = form_sub.add_parser("flatten", help="Formular fest einbrennen")
    form_flatten.add_argument("source", type=Path)
    form_flatten.add_argument("-o", "--output", required=True, type=Path)
    add_password(form_flatten)

    # -- Schutz --------------------------------------------------------
    encrypt = subparsers.add_parser("encrypt", help="PDF mit Passwort schützen")
    encrypt.add_argument("source", type=Path)
    encrypt.add_argument("-o", "--output", required=True, type=Path)
    encrypt.add_argument("--set-password", required=True, help="neues Öffnungspasswort")
    encrypt.add_argument("--owner-password")
    encrypt.add_argument("--no-printing", action="store_true")
    add_password(encrypt)

    decrypt = subparsers.add_parser("decrypt", help="Passwortschutz entfernen")
    decrypt.add_argument("source", type=Path)
    decrypt.add_argument("-o", "--output", required=True, type=Path)
    decrypt.add_argument("--password", required=True)

    compress = subparsers.add_parser("compress", help="Dateigrösse verringern")
    compress.add_argument("source", type=Path)
    compress.add_argument("-o", "--output", required=True, type=Path)
    compress.add_argument("--quality", type=int, default=70, help="Bildqualität 10-100")
    add_password(compress)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        _reject_in_place(args)
        return _dispatch(args)
    except (PdfToolError, PageSelectionError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 130


def _reject_in_place(args: argparse.Namespace) -> None:
    """Verhindert, dass die Quelldatei ihr eigenes Ziel ist.

    Beim Schreiben wird die Datei geleert, während sie noch gelesen wird --
    das Ergebnis wäre ein leeres PDF und die Vorlage unwiederbringlich weg.
    """
    output = getattr(args, "output", None)
    if output is None:
        return

    sources = getattr(args, "sources", None) or [getattr(args, "source", None)]
    sources = [Path(item) for item in sources if item is not None]
    output = Path(output)

    for source in sources:
        try:
            same = source.resolve() == output.resolve()
        except OSError:
            same = str(source) == str(output)
        if same:
            raise PdfToolError(
                f"Ziel und Quelle sind dieselbe Datei ({source.name}). "
                "Bitte einen anderen Namen für -o angeben."
            )


def _dispatch(args: argparse.Namespace) -> int:
    command = args.command

    if command == "serve":
        return _serve(args)

    if command == "info":
        data = describe(args.source, args.password)
        if args.json:
            print(json.dumps(data.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"Datei      : {data.filename}")
            print(f"Seiten     : {data.page_count}")
            print(f"Grösse     : {data.file_size / 1024:.0f} KB")
            print(f"Verschlüss.: {'ja' if data.encrypted else 'nein'}")
            print(f"Formular   : {'ja' if data.has_form else 'nein'}")
            if data.title:
                print(f"Titel      : {data.title}")
            for page in data.pages[:20]:
                print(f"  Seite {page.number:>3}: {page.width:.0f}x{page.height:.0f} pt"
                      f"{f', {page.rotation}° gedreht' if page.rotation else ''}")
            if data.page_count > 20:
                print(f"  ... und {data.page_count - 20} weitere")
        return 0

    if command == "merge":
        result = merge.merge_pdfs(
            args.sources, args.output, args.pages,
            [args.password] * len(args.sources),
            add_bookmarks=not args.no_bookmarks,
        )
        return _done(result, f"{len(args.sources)} Dateien zusammengefügt")

    if command == "split":
        if args.ranges:
            parts = split.split_by_ranges(args.source, args.output, args.ranges, args.password)
        elif args.every_page:
            parts = split.split_every_page(args.source, args.output, args.password)
        else:
            parts = split.split_into_chunks(args.source, args.output, args.chunks, args.password)
        for part in parts:
            print(f"  {part}")
        print(f"{len(parts)} Dateien erstellt.")
        return 0

    if command == "extract":
        return _done(split.extract_pages(args.source, args.output, args.pages, args.password),
                     "Seiten extrahiert")

    if command == "organize":
        return _organize(args)

    if command == "insert":
        return _done(
            organize.insert_pdf(args.source, args.addition, args.output, args.after, args.password),
            "Dokument eingefügt")

    if command == "watermark":
        return _done(edit.add_watermark(
            args.source, args.output, args.text, args.password,
            args.size, args.color, args.opacity, args.angle), "Wasserzeichen gesetzt")

    if command == "numbers":
        return _done(edit.add_page_numbers(
            args.source, args.output, args.password, args.position,
            args.size, args.start_at, args.template), "Seitenzahlen eingefügt")

    if command == "edit":
        annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
        if not isinstance(annotations, list):
            raise PdfToolError("Die JSON-Datei muss eine Liste von Elementen enthalten.")
        return _done(edit.apply_annotations(args.source, args.output, annotations, args.password),
                     f"{len(annotations)} Elemente eingefügt")

    if command == "word":
        return _done(convert.pdf_to_word(args.source, args.output, args.password, args.pages),
                     "Word-Datei erstellt")

    if command == "text":
        content = convert.pdf_to_text(args.source, args.output, args.password, args.pages, args.layout)
        if args.output:
            return _done(args.output, "Text gespeichert")
        print(content)
        return 0

    if command == "images":
        files = convert.pdf_to_images(args.source, args.output, args.password,
                                      args.pages, args.dpi, args.format)
        for path in files:
            print(f"  {path}")
        print(f"{len(files)} Bilder erstellt.")
        return 0

    if command == "from-images":
        return _done(convert.images_to_pdf(args.sources, args.output), "PDF aus Bildern erstellt")

    if command == "form":
        return _form(args)

    if command == "encrypt":
        return _done(security.encrypt(
            args.source, args.output, args.set_password, args.owner_password,
            args.password, allow_printing=not args.no_printing), "PDF verschlüsselt")

    if command == "decrypt":
        return _done(security.decrypt(args.source, args.output, args.password), "Schutz entfernt")

    if command == "compress":
        stats = security.compress(args.source, args.output, args.password, args.quality)
        saved = 100 - round(stats["ratio"] * 100)
        print(f"{stats['before'] / 1024:.0f} KB -> {stats['after'] / 1024:.0f} KB ({saved}% kleiner)")
        return _done(args.output, "Datei verkleinert")

    raise PdfToolError(f"Unbekannter Befehl: {command}")


def _organize(args: argparse.Namespace) -> int:
    """Löschen, Drehen und Sortieren nacheinander auf dieselbe Datei anwenden."""
    if not any([args.delete, args.rotate, args.order]):
        raise PdfToolError("Bitte mindestens --delete, --rotate oder --order angeben.")

    source = args.source
    steps: list[Path] = []
    target = args.output

    if args.delete:
        intermediate = target.with_suffix(".tmp-delete.pdf")
        organize.delete_pages(source, intermediate, args.delete, args.password)
        steps.append(intermediate)
        source = intermediate

    if args.rotate:
        intermediate = target.with_suffix(".tmp-rotate.pdf")
        organize.rotate_pages(source, intermediate, args.rotate, args.degrees, args.password)
        steps.append(intermediate)
        source = intermediate

    if args.order:
        organize.reorder_pages(source, target, args.order, args.password)
    else:
        Path(source).replace(target)
        steps = [step for step in steps if step != Path(source)]

    for leftover in steps:
        leftover.unlink(missing_ok=True)

    return _done(target, "Seiten organisiert")


def _form(args: argparse.Namespace) -> int:
    if args.form_command == "list":
        fields = forms.read_fields(args.source, args.password)
        if args.json:
            print(json.dumps(fields, ensure_ascii=False, indent=2))
            return 0
        if not fields:
            print("Dieses PDF enthält keine Formularfelder.")
            return 0
        width = max(len(field["name"]) for field in fields)
        for field in fields:
            options = f"  [{', '.join(map(str, field['options']))}]" if field["options"] else ""
            print(f"{field['name']:<{width}}  {field['type']:<12} "
                  f"S.{field['page']}  = {field['value']!r}{options}")
        return 0

    if args.form_command == "fill":
        values: dict[str, object] = {}
        if args.values:
            values.update(json.loads(args.values.read_text(encoding="utf-8")))
        for pair in args.set:
            if "=" not in pair:
                raise PdfToolError(f"--set erwartet FELD=WERT, bekommen: {pair!r}")
            key, value = pair.split("=", 1)
            values[key.strip()] = value
        if not values:
            raise PdfToolError("Es wurde kein Wert übergeben (--set oder --values).")

        result = forms.fill_fields(args.source, args.output, values, args.password, args.flatten)
        return _done(result, f"{len(values)} Felder ausgefüllt")

    return _done(forms.flatten_form(args.source, args.output, args.password), "Formular fixiert")


def _serve(args: argparse.Namespace) -> int:
    from .app import create_app
    from .config import Config

    host = args.host or Config.HOST
    port = args.port or Config.PORT
    url = f"http://{host}:{port}"

    print(f"PDF-Toolkit läuft auf {url}  (beenden mit Strg+C)")

    if not args.no_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    create_app().run(host=host, port=port, debug=Config.DEBUG)
    return 0


def _done(path: Path | str, message: str) -> int:
    print(f"{message}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
