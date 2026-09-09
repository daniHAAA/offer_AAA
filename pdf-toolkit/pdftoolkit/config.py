"""Einstellungen -- alle über Umgebungsvariablen mit dem Präfix PDFTOOLKIT_ übersteuerbar."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # Wo die Arbeitsbereiche liegen. Standard ist ein Ordner im Temp-Verzeichnis,
    # damit ein Neustart des Rechners automatisch aufräumt.
    WORKSPACE_ROOT = Path(
        os.environ.get("PDFTOOLKIT_WORKSPACE", Path(tempfile.gettempdir()) / "pdf-toolkit")
    )

    # Obergrenze für einen einzelnen Upload-Vorgang (Summe aller Dateien).
    MAX_CONTENT_LENGTH = int(os.environ.get("PDFTOOLKIT_MAX_UPLOAD_MB", "200")) * 1024 * 1024

    # Wie lange ein unbenutzter Arbeitsbereich aufgehoben wird.
    WORKSPACE_MAX_AGE_HOURS = float(os.environ.get("PDFTOOLKIT_RETENTION_HOURS", "12"))

    # Der Schlüssel signiert nur das Sitzungs-Cookie mit der Arbeitsbereich-ID.
    # Ohne feste Vorgabe wird beim Start ein zufälliger erzeugt -- dann sind
    # nach einem Neustart die alten Sitzungen ungültig, was lokal genau richtig ist.
    SECRET_KEY = os.environ.get("PDFTOOLKIT_SECRET_KEY") or os.urandom(32)

    HOST = os.environ.get("PDFTOOLKIT_HOST", "127.0.0.1")
    PORT = int(os.environ.get("PDFTOOLKIT_PORT", "5000"))
    DEBUG = _flag("PDFTOOLKIT_DEBUG", False)

    ALLOWED_PDF_EXTENSIONS = {".pdf"}
    ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    JSON_AS_ASCII = False
