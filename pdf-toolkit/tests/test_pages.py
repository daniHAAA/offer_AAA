"""Seitenauswahl -- die Stelle, an der Nutzereingaben zuerst auftreffen."""

import pytest

from pdftoolkit.core.pages import (
    PageSelectionError,
    format_page_selection,
    parse_page_selection,
)


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("1", [0]),
        ("1-3", [0, 1, 2]),
        ("2,4", [1, 3]),
        ("-2", [0, 1]),
        ("8-", [7, 8, 9]),
        ("all", list(range(10))),
        ("", list(range(10))),
        (None, list(range(10))),
        ("3-1", [2, 1, 0]),          # rückwärts ist erlaubt und behält die Richtung
        ("2,2,2", [1]),              # Duplikate fallen weg
        ("5-,1-2", [4, 5, 6, 7, 8, 9, 0, 1]),  # Reihenfolge bleibt wie eingegeben
    ],
)
def test_parse_valid(expression, expected):
    assert parse_page_selection(expression, 10) == expected


@pytest.mark.parametrize("expression", ["0", "11", "1-11", "abc", "1--2", "1-2-3"])
def test_parse_rejects_nonsense(expression):
    with pytest.raises(PageSelectionError):
        parse_page_selection(expression, 10)


def test_parse_rejects_empty_document():
    with pytest.raises(PageSelectionError):
        parse_page_selection("1", 0)


@pytest.mark.parametrize(
    "indices,expected",
    [([0], "1"), ([0, 1, 2], "1-3"), ([0, 2], "1,3"), ([0, 1, 4, 5, 9], "1-2,5-6,10"), ([], "")],
)
def test_format(indices, expected):
    assert format_page_selection(indices) == expected
