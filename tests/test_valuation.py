from coiner.models import CatalogEntry
from coiner.valuation import evaluate_catalog_prices


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


def test_evaluation_uses_median_of_exact_grade_eur_entries() -> None:
    entries = [
        _entry("numista", 12),
        _entry("lefranc", 18, source="lefranc"),
        _entry("wrong-grade", 50, condition="XF"),
        _entry("wrong-currency", 30, currency="USD"),
    ]

    evaluation = evaluate_catalog_prices(entries, "VF")

    assert evaluation.price == 15
    assert evaluation.currency == "EUR"
    assert {entry.id for entry in evaluation.supporting_entries} == {
        "numista",
        "lefranc",
    }


def test_evaluation_does_not_map_grades_or_convert_currencies() -> None:
    entries = [
        _entry("lefranc", 20, source="lefranc", condition="SUP"),
        _entry("usd-vf", 25, currency="USD"),
    ]

    evaluation = evaluate_catalog_prices(entries, "VF")

    assert evaluation.price is None
    assert evaluation.currency is None
    assert [entry.id for entry in evaluation.supporting_entries] == ["usd-vf"]
    assert "niet omgerekend" in evaluation.explanation
