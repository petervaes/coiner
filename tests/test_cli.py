import json
from pathlib import Path

from coiner.catalog import CatalogIndex
from coiner.cli import _exact_catalog_matches
from coiner.models import CoinIdentity


def test_price_lookup_requires_exact_country_denomination_and_known_year(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    source_file = source_dir / "coins.jsonl"
    entries = [
        {
            "id": "match",
            "title": "France 1 franc 1900",
            "country": "France",
            "denomination": "1 franc",
            "source": "numista",
            "source_url": "https://en.numista.com/catalogue/match",
            "price": 12.5,
            "currency": "EUR",
            "condition": "VF",
            "as_of": "2026-10-21",
            "year": 1900,
        },
        {
            "id": "wrong-year",
            "title": "France 1 franc 1901",
            "country": "France",
            "denomination": "1 franc",
            "source": "numista",
            "source_url": "https://en.numista.com/catalogue/wrong-year",
            "price": 15,
            "currency": "EUR",
            "condition": "VF",
            "as_of": "2026-10-21",
            "year": 1901,
        },
    ]
    source_file.write_text(
        "\n".join(json.dumps(entry) for entry in entries),
        encoding="utf-8",
    )
    catalog = CatalogIndex(tmp_path / "catalog.sqlite3")
    catalog.ingest(source_dir)

    matches = _exact_catalog_matches(
        catalog,
        CoinIdentity(country="France", denomination="1 franc", year=1900),
    )

    assert [entry["id"] for entry in matches] == ["match"]
