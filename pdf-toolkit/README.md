# PDF-Toolkit

Ein PDF-Werkzeugkasten, der **lokal auf dem eigenen Rechner** läuft. Kein Upload zu
einem fremden Dienst, keine Wasserzeichen, keine Seitenlimits – die Dateien bleiben
auf der Maschine, auf der das Programm gestartet wurde.

Bedienbar auf zwei Wegen: als Weboberfläche im Browser oder als Kommandozeilen-Werkzeug
für wiederkehrende Abläufe.

---

## Was es kann

| Werkzeug | Was es tut |
|---|---|
| **Zusammenfügen** | Mehrere PDFs aneinanderhängen, Reihenfolge per Ziehen, pro Datei nur bestimmte Seiten, Lesezeichen je Quelldokument |
| **Teilen** | Nach Seitenbereichen, jede Seite einzeln, in Blöcke fester Grösse, oder eine Auswahl extrahieren |
| **Organisieren** | Seiten als Miniaturen umsortieren, drehen, löschen; ein zweites PDF einfügen |
| **Bearbeiten** | Text, Bilder, Rahmen, Ellipsen, Linien, Markierungen und **echte Schwärzungen** setzen; Wasserzeichen und Seitenzahlen |
| **Formulare** | Felder auslesen, ausfüllen und fest einbrennen (flatten) |
| **Umwandeln** | PDF → Word (.docx), PDF → Text, PDF → Bilder, Bilder → PDF |
| **Schützen** | Passwort setzen (AES-256) oder entfernen, Dateigrösse verringern |

---

## Schnellstart

```bash
git clone <dein-repo> pdf-toolkit
cd pdf-toolkit

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run.py
```

Der Browser öffnet sich auf <http://127.0.0.1:5000>. Beenden mit `Strg+C`.

> **Word-Export ist optional.** `pdf2docx` zieht grössere Abhängigkeiten nach. Ohne
> das Paket läuft alles andere normal weiter, der Knopf „In Word" ist dann
> ausgegraut. Nachrüsten mit `pip install pdf2docx`.

---

## Kommandozeile

Für Stapelverarbeitung – etwa „alle Rechnungen eines Monats zusammenfügen und
nummerieren" – ist die CLI schneller als jede Oberfläche:

```bash
python -m pdftoolkit.cli --help          # Übersicht aller Befehle
# nach "pip install -e ." auch einfach:  pdftoolkit --help

# Zusammenfügen, aus der zweiten Datei nur die Seiten 1-3
pdftoolkit merge deckblatt.pdf bericht.pdf -o final.pdf --pages all 1-3

# Teilen
pdftoolkit split bericht.pdf -o teile/ --ranges 1-3 4-8 9-
pdftoolkit split bericht.pdf -o einzeln/ --every-page
pdftoolkit extract bericht.pdf -o auszug.pdf --pages 2,5,9-12

# Organisieren: Seite 2 und 5 raus, Seiten 1-3 drehen, dann neu sortieren
pdftoolkit organize scan.pdf -o final.pdf --delete 2,5 --rotate 1-3 --degrees 90 --order 3,1,2

# Bearbeiten
pdftoolkit watermark angebot.pdf -o entwurf.pdf --text ENTWURF --opacity 0.3
pdftoolkit numbers bericht.pdf -o nummeriert.pdf --template "Seite {page} von {total}"

# Umwandeln
pdftoolkit word bericht.pdf -o bericht.docx
pdftoolkit text bericht.pdf --pages 1-3
pdftoolkit images bericht.pdf -o bilder/ --dpi 300 --format jpg

# Formulare
pdftoolkit form list anmeldung.pdf
pdftoolkit form fill anmeldung.pdf -o fertig.pdf --set name=Daniel --set agb=true --flatten

# Schutz
pdftoolkit encrypt vertrag.pdf -o vertrag_geschuetzt.pdf --set-password geheim
pdftoolkit compress scan.pdf -o scan_klein.pdf --quality 60
```

Jeder Befehl kennt `--password`, falls das Ausgangs-PDF geschützt ist.

---

## Wie es aufgebaut ist

Drei Schichten, jede kennt nur die darunterliegende:

```
Browser (static/js/app.js)          Kommandozeile (cli.py)
            │                                │
            └──────► app.py (HTTP) ──────────┤   ← übersetzt Eingaben in Aufrufe
                          │                  │
                     storage.py              │   ← ordnet Dateien einer Sitzung zu
                          │                  │
                          └──► core/ ◄───────┘   ← die eigentliche Arbeit
```

**`pdftoolkit/core/`** kennt weder Flask noch HTTP – nur Dateipfade rein, Dateipfade
raus. Genau deshalb kann die CLI dieselbe Logik ohne Umwege benutzen, und genau
deshalb sind die Werkzeuge einzeln testbar.

| Datei | Zuständig für |
|---|---|
| `core/pages.py` | Seitenangaben wie `1-3,7,10-` verstehen |
| `core/document.py` | PDFs öffnen, entschlüsseln, beschreiben |
| `core/merge.py`, `split.py`, `organize.py` | Struktur (via **pypdf**) |
| `core/edit.py`, `render.py` | Inhalt und Darstellung (via **PyMuPDF**) |
| `core/forms.py` | Formularfelder (via **PyMuPDF**) |
| `core/convert.py` | Word, Text, Bilder (via **pdf2docx** und **PyMuPDF**) |
| `core/security.py` | Verschlüsselung und Komprimierung |
| `storage.py` | Arbeitsbereich je Browser-Sitzung |
| `app.py` | HTTP-Routen |
| `cli.py` | Kommandozeile |

### Warum zwei PDF-Bibliotheken?

Sie sind unterschiedlich gut in unterschiedlichen Dingen:

- **pypdf** arbeitet auf der Objektstruktur des PDF. Seiten kopieren, anhängen,
  drehen, verschlüsseln – dabei bleibt alles andere unangetastet.
- **PyMuPDF** rendert und zeichnet. Text setzen, Bilder einfügen, Seiten als PNG
  ausgeben, Formularfelder auslesen – dafür gibt es in pypdf kein Gegenstück.

---

## Konzepte, die man einmal verstanden haben sollte

### Seitenangaben

Überall dieselbe Schreibweise, 1-basiert wie im PDF-Betrachter:

| Eingabe | Bedeutung |
|---|---|
| `5` | nur Seite 5 |
| `2-6` | Seiten 2 bis 6 |
| `-3` | vom Anfang bis Seite 3 |
| `7-` | ab Seite 7 bis zum Ende |
| `1-3,7,10-` | kombiniert |
| `3,1,2` | Reihenfolge bleibt erhalten – so wird umsortiert |
| leer / `all` | alle Seiten |

### Ergebnisse sind wieder Eingaben

Jedes Ergebnis landet als neue Datei im Arbeitsbereich (grün markiert) und kann
sofort weiterverarbeitet werden: zusammenfügen → nummerieren → verschlüsseln, ohne
zwischendurch herunterzuladen. Das Original bleibt dabei immer unverändert.

### Schwärzen ist nicht Übermalen

Ein schwarzes Rechteck über einem Text sieht aus wie geschwärzt – der Text steht aber
weiterhin in der Datei und lässt sich markieren und kopieren. Das Werkzeug
**Schwärzen** entfernt den Inhalt tatsächlich aus dem Dokument (`apply_redactions`).
Ein Test prüft genau das: Nach der Schwärzung darf der Text nicht mehr extrahierbar
sein.

### Koordinaten als Anteil

Elemente in der Bearbeiten-Ansicht werden als Anteil der Seite gespeichert (`0.0`
bis `1.0`), nicht in Pixeln. Dadurch sitzt ein Element bei jedem Zoom und auf jedem
Seitenformat an derselben Stelle. Die Umrechnung in PDF-Punkte passiert im Server.

Für die CLI lässt sich derselbe Aufbau als JSON übergeben:

```json
[
  {"type": "text", "page": 1, "x": 0.1, "y": 0.5, "w": 0.6, "h": 0.08,
   "text": "Geprüft am 09.09.2026", "size": 14, "color": "#000000"},
  {"type": "redact", "page": 2, "x": 0.1, "y": 0.2, "w": 0.5, "h": 0.05},
  {"type": "rect", "page": 3, "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.1, "color": "#d92d20"}
]
```

```bash
pdftoolkit edit bericht.pdf -o final.pdf --annotations elemente.json
```

Typen: `text`, `image`, `rect`, `ellipse`, `line`, `highlight`, `redact`.

### Arbeitsbereich und Passwörter

Jede Browser-Sitzung bekommt einen eigenen Ordner. Dateien werden über eine
zufällige ID angesprochen, der Originalname steht nur im Manifest – dadurch kann ein
Dateiname nicht aus dem Ordner herausführen. Alte Arbeitsbereiche werden nach
zwölf Stunden automatisch gelöscht.

Passwörter geschützter PDFs bleiben **nur im Browser-Speicher** der laufenden Seite.
Sie werden weder gespeichert noch protokolliert. Nach dem Neuladen der Seite fragt
das Programm erneut.

---

## Einstellungen

Alles über Umgebungsvariablen, nichts muss im Code geändert werden:

| Variable | Standard | Wirkung |
|---|---|---|
| `PDFTOOLKIT_HOST` | `127.0.0.1` | Nur lokal erreichbar. Bewusst nicht `0.0.0.0`. |
| `PDFTOOLKIT_PORT` | `5000` | Port |
| `PDFTOOLKIT_WORKSPACE` | Temp-Ordner | Wo die Arbeitsdateien liegen |
| `PDFTOOLKIT_MAX_UPLOAD_MB` | `200` | Obergrenze je Upload |
| `PDFTOOLKIT_RETENTION_HOURS` | `12` | Aufbewahrung der Arbeitsbereiche |
| `PDFTOOLKIT_DEBUG` | `false` | Flask-Debugmodus |

---

## Tests

```bash
pip install pytest
python -m pytest -q
```

115 Tests decken Kernlogik, HTTP-Schnittstelle und CLI ab – einschliesslich der
Fälle, die schiefgehen sollen: unbekannte Formularfelder, Löschen aller Seiten,
ein Bildpfad ausserhalb des Arbeitsbereichs, Quelldatei als eigenes Ziel.
Die Test-PDFs werden zur Laufzeit erzeugt, es liegen keine Binärdateien im Repo.

---

## Grenzen

- **Keine Texterkennung (OCR).** Ein gescanntes PDF ohne Textebene liefert bei
  „In Text" und „In Word" nichts Brauchbares. Dafür bräuchte es Tesseract.
- **Bestehenden Text bearbeiten geht nicht.** Das Programm legt neue Elemente auf
  die Seite und kann Inhalte entfernen (schwärzen) – aber es ist kein
  Textverarbeitungsprogramm für vorhandene Absätze. Das kann kaum ein PDF-Werkzeug
  wirklich zuverlässig, weil ein PDF keine Absätze speichert, sondern platzierte
  Zeichen.
- **Für einen Rechner gedacht.** Der Server bindet absichtlich nur an
  `127.0.0.1`. Für den Mehrbenutzerbetrieb bräuchte es Authentifizierung und einen
  richtigen WSGI-Server.

---

## Lizenz

MIT – siehe [LICENSE](LICENSE).
