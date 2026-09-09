#!/usr/bin/env python3
"""Startet die Weboberfläche und öffnet den Browser.

    python run.py

Gleichbedeutend mit ``python -m pdftoolkit.cli serve``.
"""

import sys

from pdftoolkit.cli import main

if __name__ == "__main__":
    sys.exit(main(["serve", *sys.argv[1:]]))
