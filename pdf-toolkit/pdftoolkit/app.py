"""Flask-Anwendung: Weboberfläche und JSON-Schnittstelle.

Aufbau in drei Schichten:
  1. ``pdftoolkit.core`` -- kennt nur Dateipfade, kein Web.
  2. ``pdftoolkit.storage`` -- ordnet Dateien einer Sitzung zu.
  3. diese Datei -- übersetzt HTTP in Aufrufe der ersten beiden Schichten.

Jedes Werkzeug folgt demselben Ablauf: Eingabedatei aus dem Arbeitsbereich
holen, Kernfunktion aufrufen, Ergebnis wieder im Arbeitsbereich ablegen.
Deshalb kann jedes Ergebnis sofort Eingabe des nächsten Schritts sein.
"""

from __future__ import annotations

import io
import secrets
import zipfile
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)
from werkzeug.exceptions import RequestEntityTooLarge

from . import __version__
from .config import Config
from .core import convert, edit, forms, merge, organize, render, security, split
from .core.document import PasswordRequiredError, PdfToolError, describe
from .core.pages import PageSelectionError
from .storage import Workspace, cleanup_old_workspaces, safe_filename


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config["WORKSPACE_ROOT"].mkdir(parents=True, exist_ok=True)

    cleanup_old_workspaces(
        app.config["WORKSPACE_ROOT"], app.config["WORKSPACE_MAX_AGE_HOURS"]
    )

    _register_error_handlers(app)
    _register_routes(app)
    return app


# --------------------------------------------------------------------------
# Fehler: einheitlich als JSON, damit die Oberfläche immer dasselbe Format sieht
# --------------------------------------------------------------------------


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(PasswordRequiredError)
    def _password_required(error: PasswordRequiredError):
        # 423 Locked: Die Oberfläche fragt daraufhin gezielt nach dem Passwort.
        return jsonify({"ok": False, "error": str(error), "needs_password": True}), 423

    @app.errorhandler(PdfToolError)
    @app.errorhandler(PageSelectionError)
    def _tool_error(error: Exception):
        return jsonify({"ok": False, "error": str(error)}), 400

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(_error):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return jsonify({"ok": False, "error": f"Die Datei ist grösser als {limit} MB."}), 413

    @app.errorhandler(404)
    def _not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Unbekannte Adresse."}), 404
        return render_template("index.html", version=__version__), 404

    @app.errorhandler(500)
    def _server_error(error):
        app.logger.exception("Unerwarteter Fehler", exc_info=error)
        return jsonify({"ok": False, "error": "Unerwarteter Fehler im Server."}), 500


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def current_workspace() -> Workspace:
    """Gibt den Arbeitsbereich der Sitzung -- und legt ihn beim ersten Aufruf an."""
    workspace_id = session.get("workspace")
    if not workspace_id or not str(workspace_id).isalnum():
        workspace_id = secrets.token_hex(12)
        session["workspace"] = workspace_id
        session.permanent = False
    from flask import current_app

    return Workspace(current_app.config["WORKSPACE_ROOT"], workspace_id)


def payload() -> dict:
    return request.get_json(silent=True) or {}


def _input_path(workspace: Workspace, file_id: str | None, label: str = "Datei") -> Path:
    if not file_id:
        raise PdfToolError(f"Es wurde keine {label} ausgewählt.")
    path = workspace.path_of(str(file_id))
    if path is None:
        raise PdfToolError("Die gewählte Datei ist nicht mehr im Arbeitsbereich.")
    return path


def _result_name(source_name: str, suffix: str, extension: str = ".pdf") -> str:
    return f"{Path(source_name).stem}_{suffix}{extension}"


def _deliver(workspace: Workspace, path: Path, name: str, origin: str):
    """Registriert ein Ergebnis und antwortet einheitlich."""
    entry = workspace.add_result(path, name, origin)
    return jsonify({"ok": True, "file": entry.to_dict()})


def _zip_files(paths: list[Path], target: Path) -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
    return target


# --------------------------------------------------------------------------
# Routen
# --------------------------------------------------------------------------


def _register_routes(app: Flask) -> None:
    @app.get("/")
    def index():
        return render_template("index.html", version=__version__)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "version": __version__, "word_export": _word_available()})

    # -- Dateien ------------------------------------------------------

    @app.post("/api/upload")
    def upload():
        workspace = current_workspace()
        uploads = request.files.getlist("files")
        if not uploads:
            raise PdfToolError("Es wurde keine Datei übertragen.")

        allowed = (
            app.config["ALLOWED_PDF_EXTENSIONS"] | app.config["ALLOWED_IMAGE_EXTENSIONS"]
        )
        stored = []

        for upload_file in uploads:
            name = safe_filename(upload_file.filename or "")
            if Path(name).suffix.lower() not in allowed:
                raise PdfToolError(
                    f"{name}: nur PDF- und Bilddateien werden angenommen."
                )
            stored.append(workspace.add_upload(upload_file, name).to_dict())

        return jsonify({"ok": True, "files": stored})

    @app.get("/api/files")
    def list_files():
        workspace = current_workspace()
        return jsonify({"ok": True, "files": [item.to_dict() for item in workspace.list_files()]})

    @app.delete("/api/files/<file_id>")
    def delete_file(file_id: str):
        workspace = current_workspace()
        if not workspace.delete(file_id):
            raise PdfToolError("Die Datei ist bereits weg.")
        return jsonify({"ok": True})

    @app.post("/api/files/clear")
    def clear_files():
        current_workspace().clear()
        return jsonify({"ok": True})

    @app.get("/api/files/<file_id>/download")
    def download(file_id: str):
        workspace = current_workspace()
        entry = workspace.get(file_id)
        path = _input_path(workspace, file_id)
        return send_file(path, as_attachment=True, download_name=entry.name if entry else path.name)

    @app.get("/api/files/<file_id>/info")
    def info(file_id: str):
        workspace = current_workspace()
        path = _input_path(workspace, file_id)
        password = request.args.get("password") or None
        data = describe(path, password).to_dict()
        data["id"] = file_id
        return jsonify({"ok": True, "info": data})

    @app.get("/api/files/<file_id>/page/<int:page_number>.png")
    def page_preview(file_id: str, page_number: int):
        workspace = current_workspace()
        path = _input_path(workspace, file_id)
        width = min(max(int(request.args.get("width", 700)), 60), 2000)
        image = render.render_page(path, page_number, request.args.get("password") or None, width)
        return send_file(io.BytesIO(image), mimetype="image/png")

    # -- Zusammenfügen -------------------------------------------------

    @app.post("/api/merge")
    def api_merge():
        workspace = current_workspace()
        data = payload()
        items = data.get("files") or []
        if len(items) < 2:
            raise PdfToolError("Zum Zusammenfügen werden mindestens zwei PDFs gebraucht.")

        sources = [_input_path(workspace, item.get("id")) for item in items]
        selections = [item.get("pages") for item in items]
        passwords = [item.get("password") for item in items]

        target = workspace.temp_dir("merge") / "zusammengefuegt.pdf"
        merge.merge_pdfs(
            sources, target, selections, passwords,
            add_bookmarks=bool(data.get("bookmarks", True)),
        )
        name = safe_filename(data.get("name") or "zusammengefuegt.pdf")
        return _deliver(workspace, target, name, "Zusammenfügen")

    # -- Teilen --------------------------------------------------------

    @app.post("/api/split")
    def api_split():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        stem = Path(entry.name).stem if entry else source.stem
        password = data.get("password")
        mode = str(data.get("mode", "ranges"))
        output = workspace.temp_dir("split")

        if mode == "ranges":
            parts = split.split_by_ranges(source, output, data.get("ranges") or [], password, stem)
        elif mode == "every":
            parts = split.split_every_page(source, output, password, stem)
        elif mode == "chunks":
            parts = split.split_into_chunks(
                source, output, int(data.get("chunk_size", 10)), password, stem
            )
        elif mode == "extract":
            target = output / _result_name(stem + ".pdf", "auswahl")
            split.extract_pages(source, target, str(data.get("pages") or ""), password)
            return _deliver(workspace, target, target.name, "Seiten extrahieren")
        else:
            raise PdfToolError(f"Unbekannter Teilen-Modus: {mode}")

        if len(parts) == 1:
            return _deliver(workspace, parts[0], parts[0].name, "Teilen")

        archive = _zip_files(parts, output / f"{stem}_geteilt.zip")
        response = _deliver(workspace, archive, archive.name, "Teilen")
        return response

    # -- Organisieren --------------------------------------------------

    @app.post("/api/organize")
    def api_organize():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("organize") / _result_name(name, "organisiert")
        organize.apply_layout(source, target, data.get("layout") or [], data.get("password"))
        return _deliver(workspace, target, target.name, "Organisieren")

    @app.post("/api/insert")
    def api_insert():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        addition = _input_path(workspace, data.get("insert_file"), "einzufügende Datei")
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("insert") / _result_name(name, "eingefuegt")
        organize.insert_pdf(
            source, addition, target, int(data.get("after_page", 0)),
            data.get("password"), data.get("insert_password"),
        )
        return _deliver(workspace, target, target.name, "Einfügen")

    # -- Bearbeiten ----------------------------------------------------

    @app.post("/api/edit")
    def api_edit():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        annotations = list(data.get("annotations") or [])
        for annotation in annotations:
            # Ein Bildelement verweist auf eine Datei im Arbeitsbereich, nie auf
            # einen freien Pfad -- sonst könnte der Client jede Datei einlesen.
            if str(annotation.get("type", "")).lower() == "image":
                annotation["image_path"] = str(
                    _input_path(workspace, annotation.get("image_id"), "Bilddatei")
                )

        target = workspace.temp_dir("edit") / _result_name(name, "bearbeitet")
        edit.apply_annotations(source, target, annotations, data.get("password"))
        return _deliver(workspace, target, target.name, "Bearbeiten")

    @app.post("/api/watermark")
    def api_watermark():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("watermark") / _result_name(name, "wasserzeichen")
        edit.add_watermark(
            source, target,
            text=str(data.get("text", "")),
            password=data.get("password"),
            font_size=int(data.get("size", 48)),
            color=str(data.get("color", "#c8c8c8")),
            opacity=float(data.get("opacity", 0.35)),
            angle=int(data.get("angle", 45)),
        )
        return _deliver(workspace, target, target.name, "Wasserzeichen")

    @app.post("/api/page-numbers")
    def api_page_numbers():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("numbers") / _result_name(name, "nummeriert")
        edit.add_page_numbers(
            source, target,
            password=data.get("password"),
            position=str(data.get("position", "bottom-center")),
            font_size=int(data.get("size", 10)),
            start_at=int(data.get("start_at", 1)),
            template=str(data.get("template", "{page}")),
        )
        return _deliver(workspace, target, target.name, "Seitenzahlen")

    # -- Umwandeln -----------------------------------------------------

    @app.post("/api/convert/word")
    def api_word():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("word") / _result_name(name, "export", ".docx")
        convert.pdf_to_word(source, target, data.get("password"), data.get("pages"))
        return _deliver(workspace, target, target.name, "PDF in Word")

    @app.post("/api/convert/text")
    def api_text():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("text") / _result_name(name, "text", ".txt")
        content = convert.pdf_to_text(
            source, target, data.get("password"), data.get("pages"), bool(data.get("layout"))
        )
        result = _deliver(workspace, target, target.name, "PDF in Text")
        body = result.get_json()
        body["preview"] = content[:4000]
        return jsonify(body)

    @app.post("/api/convert/images")
    def api_images():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        stem = Path(entry.name).stem if entry else source.stem

        output = workspace.temp_dir("images")
        images = convert.pdf_to_images(
            source, output, data.get("password"), data.get("pages"),
            int(data.get("dpi", 150)), str(data.get("format", "png")), stem,
        )
        if len(images) == 1:
            return _deliver(workspace, images[0], images[0].name, "PDF in Bilder")

        archive = _zip_files(images, output / f"{stem}_bilder.zip")
        return _deliver(workspace, archive, archive.name, "PDF in Bilder")

    @app.post("/api/convert/images-to-pdf")
    def api_images_to_pdf():
        workspace = current_workspace()
        data = payload()
        ids = data.get("files") or []
        if not ids:
            raise PdfToolError("Es wurde kein Bild ausgewählt.")

        sources = [_input_path(workspace, file_id, "Bilddatei") for file_id in ids]
        target = workspace.temp_dir("img2pdf") / safe_filename(
            str(data.get("name") or "bilder.pdf")
        )
        convert.images_to_pdf(sources, target)
        return _deliver(workspace, target, target.name, "Bilder in PDF")

    # -- Formulare -----------------------------------------------------

    @app.get("/api/forms/<file_id>")
    def api_form_fields(file_id: str):
        workspace = current_workspace()
        path = _input_path(workspace, file_id)
        fields = forms.read_fields(path, request.args.get("password") or None)
        return jsonify({"ok": True, "fields": fields})

    @app.post("/api/forms/<file_id>/fill")
    def api_form_fill(file_id: str):
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, file_id)
        entry = workspace.get(file_id)
        name = entry.name if entry else source.name

        target = workspace.temp_dir("form") / _result_name(name, "ausgefuellt")
        forms.fill_fields(
            source, target, data.get("values") or {},
            data.get("password"), bool(data.get("flatten")),
        )
        return _deliver(workspace, target, target.name, "Formular ausfüllen")

    @app.post("/api/forms/<file_id>/flatten")
    def api_form_flatten(file_id: str):
        workspace = current_workspace()
        source = _input_path(workspace, file_id)
        entry = workspace.get(file_id)
        name = entry.name if entry else source.name

        target = workspace.temp_dir("form") / _result_name(name, "fixiert")
        forms.flatten_form(source, target, payload().get("password"))
        return _deliver(workspace, target, target.name, "Formular fixieren")

    # -- Schutz und Grösse ---------------------------------------------

    @app.post("/api/security/encrypt")
    def api_encrypt():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("secure") / _result_name(name, "geschuetzt")
        security.encrypt(
            source, target,
            user_password=str(data.get("user_password", "")),
            owner_password=data.get("owner_password") or None,
            password=data.get("password"),
            allow_printing=bool(data.get("allow_printing", True)),
        )
        return _deliver(workspace, target, target.name, "Verschlüsseln")

    @app.post("/api/security/decrypt")
    def api_decrypt():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("secure") / _result_name(name, "offen")
        security.decrypt(source, target, str(data.get("password", "")))
        return _deliver(workspace, target, target.name, "Schutz entfernen")

    @app.post("/api/compress")
    def api_compress():
        workspace = current_workspace()
        data = payload()
        source = _input_path(workspace, data.get("file"))
        entry = workspace.get(str(data.get("file")))
        name = entry.name if entry else source.name

        target = workspace.temp_dir("compress") / _result_name(name, "klein")
        stats = security.compress(
            source, target, data.get("password"),
            int(data.get("quality", 70)), int(data.get("dpi", 150)),
        )
        result = _deliver(workspace, target, target.name, "Komprimieren")
        body = result.get_json()
        body["stats"] = stats
        return jsonify(body)


def _word_available() -> bool:
    try:
        import pdf2docx  # noqa: F401
    except ImportError:
        return False
    return True


app = create_app()
