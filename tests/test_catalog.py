import json
import shutil
from pathlib import Path

import pytest

from coiner.catalog import CatalogIndex
from coiner.models import CatalogEntry


def _entry(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "numista-fr-1-franc-1900",
        "title": "France 1 franc 1900",
        "country": "France",
        "denomination": "1 franc",
        "source": "numista",
        "source_url": "https://en.numista.com/catalogue/example",
        "price": 12.5,
        "currency": "EUR",
        "condition": "VF",
        "as_of": "2026-10-21",
        "year": 1900,
        "catalog_reference": "KM# 844",
    }
    data.update(overrides)
    return data


def test_catalog_entry_validates_and_normalizes_currency() -> None:
    entry = CatalogEntry.from_dict(_entry(currency="eur"))

    assert entry.currency == "EUR"
    assert entry.price == 12.5


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_url": "http://example.org/coin"}, "HTTPS"),
        ({"currency": "EURO"}, "three-letter"),
        ({"price": -1}, "cannot be negative"),
        ({"price": float("nan")}, "finite"),
        ({"price": True}, "must be a number"),
        ({"as_of": "21-10-2026"}, "ISO date"),
    ],
)
def test_catalog_entry_rejects_invalid_source_data(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CatalogEntry.from_dict(_entry(**overrides))


def test_ingest_and_search_return_source_attributed_price(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    source_file = source_dir / "france.jsonl"
    source_file.write_text(json.dumps(_entry()), encoding="utf-8")
    index = CatalogIndex(tmp_path / "data" / "catalog.sqlite3")

    assert index.ingest(source_dir) == 1
    results = index.search("France 1 franc 1900")

    assert len(results) == 1
    assert results[0].source == "numista"
    assert results[0].source_url == "https://en.numista.com/catalogue/example"
    assert results[0].price == 12.5


def test_ingest_rejects_bad_line_with_file_and_line_number(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "invalid.jsonl").write_text("{}\n", encoding="utf-8")
    index = CatalogIndex(tmp_path / "catalog.sqlite3")

    with pytest.raises(ValueError, match=r"invalid\.jsonl:1:"):
        index.ingest(source_dir)


def test_rebuild_removes_old_entries(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    source_file = source_dir / "france.jsonl"
    source_file.write_text(json.dumps(_entry()), encoding="utf-8")
    index = CatalogIndex(tmp_path / "catalog.sqlite3")
    index.ingest(source_dir)
    source_file.write_text(json.dumps(_entry(id="different-id")), encoding="utf-8")

    index.ingest(source_dir, clear=True)

    assert len(index.search("France 1 franc 1900")) == 1


def test_numista_table_import_expands_grade_prices_and_keeps_metadata(
    tmp_path: Path,
) -> None:
    project_catalog = Path(__file__).parents[1] / "catalog" / "catalog.json"
    numista_catalog = tmp_path / "numista"
    numista_catalog.mkdir()
    shutil.copyfile(project_catalog, numista_catalog / project_catalog.name)
    index = CatalogIndex(tmp_path / "numista.sqlite3")

    assert index.ingest(numista_catalog) == 68
    results = index.search(
        "France 1 franc Morlon 1935",
        limit=10,
        country="France",
        denomination="1 franc",
        year=1935,
    )

    assert {entry.condition: entry.price for entry in results} == {
        "VF": 12.0,
        "XF": 15.0,
        "AU": 19.0,
    }
    assert all(entry.mintage == 1_166_038 for entry in results)
    assert all(entry.frequency_percent == 7 for entry in results)
    assert all(entry.mint_mark == "Wing" for entry in results)
    assert all(
        entry.related_source_url
        == "https://www.lefranc.net/monnaie,numista,219.html"
        for entry in results
    )


def test_catalog_rejects_invalid_grade_price_object(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "invalid.json").write_text(
        json.dumps([{"id": "invalid", "prices": []}]),
        encoding="utf-8",
    )
    index = CatalogIndex(tmp_path / "catalog.sqlite3")

    with pytest.raises(ValueError, match="prices must be a non-empty"):
        index.ingest(source_dir)
