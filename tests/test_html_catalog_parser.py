import json
from pathlib import Path

import pytest

from coiner.catalog import CatalogIndex
from coiner.cli import main
from coiner.html_catalog_parser import (
    HTMLCatalogParseError,
    parse_coin_catalog_file,
    parse_coin_catalog_html,
)


def test_parses_numista_style_year_grade_table() -> None:
    html = """
    <html><head><title>France 1 franc Morlon</title></head><body>
      <table>
        <tr><th>Date</th><th>Mintage</th><th>G</th><th>VG</th><th>F</th><th>VF</th></tr>
        <tr><td>1935</td><td>1 166 038</td><td></td><td></td><td></td><td>€ 12,00</td></tr>
        <tr><td>1936</td><td>23.816.782</td><td>€ 0,18</td><td>€ 0,18</td>
            <td>€ 0,25</td><td>€ 0,49</td></tr>
      </table>
    </body></html>
    """

    records = parse_coin_catalog_html(
        html,
        source="numista",
        source_url="https://en.numista.com/catalogue/example",
        country="France",
        denomination="1 franc",
        capture_date="2026-10-21",
    )

    assert len(records) == 2
    assert records[0]["year"] == 1935
    assert records[0]["prices"] == {"VF": 12.0}
    assert records[0]["mintage"] == 1_166_038
    assert records[1]["year"] == 1936
    assert records[1]["prices"] == {
        "G": 0.18,
        "VG": 0.18,
        "F": 0.25,
        "VF": 0.49,
    }
    assert "captured on 2026-10-21" in str(records[0]["notes"])


def test_parses_french_lefranc_grade_labels_and_european_numbers() -> None:
    html = """
    <html><head><title>LeFranc - 1 franc</title></head><body>
      <table>
        <thead><tr><th>Année</th><th>Tirage</th><th>B</th><th>TB</th>
          <th>TTB</th><th>SUP</th><th>SPL</th><th>FDC</th></tr></thead>
        <tbody><tr><td>1935</td><td>1.166.038</td><td>10,00 €</td>
          <td>25,00 €</td><td>45,00 €</td><td>120,00 €</td>
          <td>300,00 €</td><td>500,00 €</td></tr></tbody>
      </table>
    </body></html>
    """

    records = parse_coin_catalog_html(
        html,
        source="lefranc",
        source_url="https://www.lefranc.net/monnaie,1-franc-morlon,219.html",
        country="France",
        denomination="1 franc",
        capture_date="2026-10-21",
    )

    assert len(records) == 1
    assert records[0]["prices"] == {
        "B": 10.0,
        "TB": 25.0,
        "TTB": 45.0,
        "SUP": 120.0,
        "SPL": 300.0,
        "FDC": 500.0,
    }
    assert records[0]["mintage"] == 1_166_038


def test_splits_currencies_when_values_are_explicit_per_cell() -> None:
    html = """
    <table>
      <tr><th>Year</th><th>VF</th><th>XF</th></tr>
      <tr><td>1935</td><td>€ 12,00</td><td>$ 15.00</td></tr>
    </table>
    """
    records = parse_coin_catalog_html(
        html,
        source="numista",
        source_url="https://en.numista.com/catalogue/example",
        country="France",
        denomination="1 franc",
        currency="EUR",
    )

    assert {record["currency"] for record in records} == {"EUR", "USD"}
    assert {json.dumps(record["prices"], sort_keys=True) for record in records} == {
        '{"VF": 12.0}',
        '{"XF": 15.0}',
    }


def test_parses_vertical_grade_and_price_tables() -> None:
    html = """
    <table>
      <tr><th>Grade</th><th>Prix</th><th>Year</th></tr>
      <tr><td>B</td><td>€ 10,00</td><td>1935</td></tr>
      <tr><td>TB</td><td>€ 25,00</td><td>1935</td></tr>
      <tr><td>TTB</td><td>€ 45,00</td><td>1935</td></tr>
    </table>
    """

    records = parse_coin_catalog_html(
        html,
        source="lefranc",
        source_url="https://www.lefranc.net/coin",
        country="France",
        denomination="1 franc",
    )

    assert [record["prices"] for record in records] == [
        {"B": 10},
        {"TB": 25},
        {"TTB": 45},
    ]
    assert all(record["year"] == 1935 for record in records)


def test_rejects_unsupported_or_unparseable_html() -> None:
    options = {
        "source": "lefranc",
        "source_url": "https://www.lefranc.net/coin",
        "country": "France",
        "denomination": "1 franc",
    }
    with pytest.raises(HTMLCatalogParseError, match="No grade-price table"):
        parse_coin_catalog_html("<html><p>No coin prices</p></html>", **options)
    with pytest.raises(HTMLCatalogParseError, match="source must"):
        parse_coin_catalog_html(
            "<table></table>", **{**options, "source": "other"}
        )
    with pytest.raises(HTMLCatalogParseError, match="capture_date"):
        parse_coin_catalog_html(
            "<table></table>",
            **options,
            capture_date="21-10-2026",
        )


def test_parse_file_and_cli_write_catalog_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    html_path = tmp_path / "coin.html"
    html_path.write_text(
        "<table><tr><th>Year</th><th>VF</th></tr>"
        "<tr><td>1935</td><td>€12.00</td></tr></table>",
        encoding="utf-8",
    )
    output_path = tmp_path / "parsed.json"

    main(
        [
            "parse-html",
            str(html_path),
            "--source",
            "numista",
            "--source-url",
            "https://en.numista.com/catalogue/example",
            "--country",
            "France",
            "--denomination",
            "1 franc",
            "--capture-date",
            "2026-10-21",
            "--output",
            str(output_path),
        ]
    )

    assert json.loads(output_path.read_text(encoding="utf-8"))[0]["prices"] == {
        "VF": 12.0
    }
    assert json.loads(capsys.readouterr().out)["parsed_records"] == 1


def test_parsed_records_can_be_ingested_by_catalog_index(tmp_path: Path) -> None:
    records = parse_coin_catalog_html(
        """
        <table><tr><th>Year</th><th>F (Fine)</th><th>VF</th></tr>
        <tr><td>1935</td><td>€ 10.00</td><td>€ 12.00</td></tr></table>
        """,
        source="numista",
        source_url="https://en.numista.com/catalogue/example",
        country="France",
        denomination="1 franc",
        capture_date="2026-10-21",
    )
    catalog_dir = tmp_path / "imports"
    catalog_dir.mkdir()
    (catalog_dir / "parsed.json").write_text(
        json.dumps(records), encoding="utf-8"
    )
    catalog = CatalogIndex(tmp_path / "catalog.sqlite3")

    assert catalog.ingest(catalog_dir) == 2
    entries = catalog.search(
        "France 1 franc 1935",
        country="France",
        denomination="1 franc",
        year=1935,
        limit=5,
    )

    assert {entry.condition: entry.price for entry in entries} == {
        "F (Fine)": 10,
        "VF": 12,
    }


def test_invalid_utf8_file_reports_actionable_error(tmp_path: Path) -> None:
    html_file = tmp_path / "not-utf8.html"
    html_file.write_bytes(b"\xff\xfe")

    with pytest.raises(HTMLCatalogParseError, match="not UTF-8"):
        parse_coin_catalog_file(
            html_file,
            source="lefranc",
            source_url="https://www.lefranc.net/coin",
            country="France",
            denomination="1 franc",
        )
