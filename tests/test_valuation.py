from pathlib import Path

import pytest

from coiner.catalog import CatalogIndex
from coiner.models import CatalogEntry
from coiner.valuation import (
    canonical_grade,
    evaluate_catalog_prices,
    matching_grade_rank,
    select_nearest_matches,
)


def _entry(identifier: str, price: float, **overrides: object) -> CatalogEntry:
    data: dict[str, object] = {
        "id": identifier,
        "title": "France 1 franc Morlon 1935",
        "country": "France",
        "denomination": "1 franc",
        "source": "numista",
        "source_url": "https://en.numista.com/catalogue/example",
        "price": price,
        "currency": "EUR",
        "condition": "VF",
        "as_of": "2026-10-21",
        "year": 1935,
    }
    data.update(overrides)
    return CatalogEntry.from_dict(data)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("B", "F"),
        ("Beau", "F"),
        ("B (Beau)", "F"),
        ("F", "F"),
        ("Fine", "F"),
        ("TB", "VG"),
        ("Très Beau", "VG"),
        ("TTB", "VF"),
        ("Très Très Beau", "VF"),
        ("SUP", "XF"),
        ("Superbe", "XF"),
        ("SPL", "AU"),
        ("FDC", "UNC"),
        ("Mint State", "UNC"),
    ],
)
def test_french_and_english_grade_labels_normalize(
    label: str, expected: str
) -> None:
    assert canonical_grade(label) == expected


def test_beau_matches_numista_fine_as_requested() -> None:
    numista = _entry("numista-f", 12, condition="F")
    lefranc = _entry("lefranc-b", 9, source="lefranc", condition="B")

    assert matching_grade_rank(numista, "B") == 1
    assert matching_grade_rank(lefranc, "F") == 1
    evaluations = evaluate_catalog_prices([numista, lefranc], "B")

    assert [(item.source, item.currency, item.price) for item in evaluations] == [
        ("lefranc", "EUR", 9),
        ("numista", "EUR", 12),
    ]


def test_french_and_numista_grade_matches_are_evaluated_per_source() -> None:
    entries = [
        _entry("numista-vf", 12),
        _entry("lefranc-ttb", 18, source="lefranc", condition="TTB"),
        _entry("lefranc-usd", 20, source="lefranc", condition="TTB", currency="USD"),
        _entry("wrong-grade", 50, source="lefranc", condition="SUP"),
    ]

    evaluations = evaluate_catalog_prices(entries, "VF")

    assert [(item.source, item.currency, item.price) for item in evaluations] == [
        ("lefranc", "EUR", 18),
        ("lefranc", "USD", 20),
        ("numista", "EUR", 12),
    ]
    assert all(item.canonical_grade == "VF" for item in evaluations)


def test_bundled_1935_catalog_shows_numista_and_lefranc_vf_equivalents(
    tmp_path: Path,
) -> None:
    catalog_dir = Path(__file__).parents[1] / "catalog"
    catalog = CatalogIndex(tmp_path / "catalog.sqlite3")
    catalog.ingest(catalog_dir)
    candidates = catalog.search(
        "France 1 franc 1935",
        limit=100,
        country="France",
        denomination="1 franc",
        year=1935,
    )

    evaluations = evaluate_catalog_prices(candidates, "VF")
    prices = {
        (evaluation.source, evaluation.currency): evaluation.price
        for evaluation in evaluations
    }

    assert prices == {
        ("lefranc", "EUR"): 45.0,
        ("lefranc", "USD"): 50.4,
        ("numista", "EUR"): 12.0,
    }
    assert {entry.source for entry in select_nearest_matches(candidates, "VF")} == {
        "lefranc",
        "numista",
    }


def test_nearest_matches_keep_both_sources_visible() -> None:
    entries = [
        _entry("lefranc-vf", 18, source="lefranc", condition="TTB"),
        _entry("lefranc-sup", 30, source="lefranc", condition="SUP"),
        _entry("numista-vf", 12),
        _entry("numista-xf", 15, condition="XF"),
    ]

    selected = select_nearest_matches(entries, "VF", limit=3)

    assert len(selected) == 3
    assert {entry.source for entry in selected} == {"lefranc", "numista"}
    assert selected[0].condition == "VF"
    assert selected[1].condition == "TTB"


def test_unknown_or_unmatched_grades_do_not_generate_prices() -> None:
    entries = [
        _entry("lefranc-sup", 30, source="lefranc", condition="SUP"),
    ]

    assert canonical_grade("mystery") is None
    assert evaluate_catalog_prices(entries, "mystery") == []
    assert evaluate_catalog_prices(entries, "VF") == []


def test_match_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        select_nearest_matches([], "VF", limit=0)
