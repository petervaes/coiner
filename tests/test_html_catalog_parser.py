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


def test_parses_lefranc_spanned_headers_and_eur_usd_price_pairs() -> None:
    html = """
    <html><head><title>Pièce de monnaie 5 Francs SEMEUSE, ARGENT</title></head>
    <body><table>
      <tr>
        <td rowspan="2">N° de FRANC</td><td rowspan="2">Date</td>
        <td rowspan="2">Atelier</td><td colspan="6">Prix en Euros Dollars</td>
        <td rowspan="2">Grade dans la Collection Idéale</td>
      </tr>
      <tr><td>B 10 (€)</td><td>TB 25 (€)</td><td>TTB 45 (€)</td>
        <td>SUP 58 (€)</td><td>SPL 63 (€)</td><td>FDC 65 (€)</td></tr>
      <tr><td>F.340/4</td><td>1960</td><td></td><td>-</td><td>-</td>
        <td>-</td><td>-</td><td><span>13,00</span><span>14,56</span></td>
        <td><span>50,00</span><span>56,00</span></td><td>67</td></tr>
    </table></body></html>
    """

    records = parse_coin_catalog_html(
        html,
        source="lefranc",
        source_url="https://www.lefranc.net/monnaie,numista,340.html",
        country="France",
        denomination="5 francs",
        capture_date="2026-10-21",
    )

    by_currency = {record["currency"]: record for record in records}
    assert len(records) == 2
    assert by_currency["EUR"]["prices"] == {"SPL": 13.0, "FDC": 50.0}
    assert by_currency["USD"]["prices"] == {"SPL": 14.56, "FDC": 56.0}
    assert by_currency["EUR"]["catalog_reference"] == "F.340/4"
    assert by_currency["EUR"]["collection_grade"] == "67"
    assert by_currency["EUR"]["year"] == 1960


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


def test_imported_5_francs_1960_snapshot_has_both_currency_series(
    tmp_path: Path,
) -> None:
    catalog_dir = Path(__file__).parents[1] / "catalog"
    catalog = CatalogIndex(tmp_path / "catalog.sqlite3")
    catalog.ingest(catalog_dir)
    entries = catalog.search(
        "France 5 francs 1960",
        country="France",
        denomination="5 francs",
        year=1960,
        limit=10,
    )
    prices = {
        (entry.currency, entry.condition): entry.price
        for entry in entries
        if entry.source == "lefranc"
    }

    assert prices == {
        ("EUR", "SPL"): 13,
        ("EUR", "FDC"): 50,
        ("USD", "SPL"): 14.56,
        ("USD", "FDC"): 56,
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
