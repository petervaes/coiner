import json
import sqlite3
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from coiner.catalog import CatalogIndex
from coiner.catalog_fallback import (
    CatalogFallbackError,
    _AllowlistedRedirectHandler,
    _get_bytes,
    _google_lefranc_urls,
    _lefranc_index_urls,
    _numista_api_records,
    resolve_catalog_miss,
)
from coiner.models import CoinIdentity


def test_lefranc_fallback_downloads_parses_persists_and_cleans_temp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("NUMISTA_API_KEY", raising=False)
    html = b"""
    <html><head><title>France 5 francs Semeuse</title></head><body>
    <table><tr><th>Year</th><th>VF</th><th>XF</th></tr>
    <tr><td>1960</td><td>EUR 2,00</td><td>EUR 5,00</td></tr>
    </table></body></html>
    """
    monkeypatch.setattr(
        "coiner.catalog_fallback._google_lefranc_urls",
        lambda _identity: ["https://www.lefranc.net/monnaie,coin,123.html"],
    )
    monkeypatch.setattr(
        "coiner.catalog_fallback._get_bytes",
        lambda *_args, **_kwargs: html,
    )
    index = CatalogIndex(tmp_path / "data" / "catalog.sqlite3")
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()

    result = resolve_catalog_miss(
        CoinIdentity(country="France", denomination="5 francs", year=1960),
        catalog=index,
        catalog_dir=catalog_dir,
    )

    assert {(entry.condition, entry.price) for entry in result.entries} == {
        ("VF", 2),
        ("XF", 5),
    }
    assert len(list((catalog_dir / "imports").glob("*.json"))) == 1
    assert not list(tmp_path.glob("coiner-lefranc-*"))
    assert not list(tmp_path.glob("*.html"))


def test_numista_api_parser_stores_metadata_without_fabricating_prices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("NUMISTA_API_KEY", "test-api-key")
    monkeypatch.setattr(
        "coiner.catalog_fallback._get_bytes",
        lambda *_args, **_kwargs: json.dumps(
            {
                "types": [
                    {
                        "id": 123,
                        "title": "5 francs Semeuse",
                        "year": 1960,
                        "issuer": "France",
                        "reference": "F.340/4",
                        "prices": {"VF": 12},
                    }
                ]
            }
        ).encode(),
    )

    metadata, prices = _numista_api_records(
        CoinIdentity(country="France", denomination="5 francs", year=1960),
        capture_date="2026-10-21",
    )

    assert len(metadata) == 1
    assert metadata[0]["catalog_reference"] == "F.340/4"
    assert metadata[0]["source_url"].endswith("pieces123.html")
    assert prices == []
    assert not list(tmp_path.glob("coiner-numista-*"))


def test_numista_metadata_is_saved_to_json_and_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NUMISTA_API_KEY", raising=False)
    monkeypatch.setattr(
        "coiner.catalog_fallback._numista_api_records",
        lambda *_args, **_kwargs: (
            [
                {
                    "id": "numista-type-123",
                    "source": "numista",
                    "country": "France",
                    "denomination": "5 francs",
                    "year": 1960,
                    "title": "5 francs Semeuse",
                }
            ],
            [],
        ),
    )
    monkeypatch.setattr(
        "coiner.catalog_fallback._google_lefranc_urls", lambda _identity: []
    )
    monkeypatch.setattr(
        "coiner.catalog_fallback._lefranc_index_urls", lambda _identity: []
    )
    index = CatalogIndex(tmp_path / "catalog.sqlite3")
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()

    result = resolve_catalog_miss(
        CoinIdentity(country="France", denomination="5 francs", year=1960),
        catalog=index,
        catalog_dir=catalog_dir,
    )

    metadata_file = next((catalog_dir / "imports").glob("*.metadata.json"))
    assert json.loads(metadata_file.read_text(encoding="utf-8"))[0]["id"] == (
        "numista-type-123"
    )
    with sqlite3.connect(index.database) as connection:
        stored = connection.execute(
            "SELECT metadata_json FROM coin_metadata WHERE id = ?",
            ("numista-type-123",),
        ).fetchone()
    assert stored is not None
    assert json.loads(stored[0])["year"] == 1960
    assert result.metadata[0]["title"] == "5 francs Semeuse"


def test_downloader_does_not_retry_or_bypass_http_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise HTTPError(
            "https://www.lefranc.net/coin",
            403,
            "Forbidden",
            {},
            None,
        )

    class ForbiddenOpener:
        def open(self, *_args: object, **_kwargs: object) -> None:
            forbidden()

    monkeypatch.setattr(
        "coiner.catalog_fallback.build_opener",
        lambda *_handlers: ForbiddenOpener(),
    )

    with pytest.raises(CatalogFallbackError, match="HTTP 403"):
        _get_bytes(
            "https://www.lefranc.net/coin",
            hosts={"www.lefranc.net"},
        )

    assert calls == 1


def test_downloader_rejects_non_allowlisted_hosts() -> None:
    with pytest.raises(CatalogFallbackError, match="allowlist"):
        _get_bytes(
            "https://attacker.example/coin",
            hosts={"www.lefranc.net"},
        )


def test_redirect_handler_blocks_off_host_redirect_before_following() -> None:
    handler = _AllowlistedRedirectHandler({"www.lefranc.net"})

    with pytest.raises(CatalogFallbackError, match="redirected outside"):
        handler.redirect_request(
            Request("https://www.lefranc.net/start"),
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )


def test_lefranc_temp_file_is_removed_when_parsing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("NUMISTA_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    monkeypatch.setattr(
        "coiner.catalog_fallback._lefranc_index_urls", lambda _identity: []
    )
    monkeypatch.setattr(
        "coiner.catalog_fallback._get_bytes",
        lambda *_args, **_kwargs: b"<html><body>not a catalog table</body></html>",
    )
    monkeypatch.setattr(
        "coiner.catalog_fallback._google_lefranc_urls",
        lambda _identity: ["https://www.lefranc.net/monnaie,coin,123.html"],
    )
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()

    resolve_catalog_miss(
        CoinIdentity(country="France", denomination="5 francs", year=1960),
        catalog=CatalogIndex(tmp_path / "catalog.sqlite3"),
        catalog_dir=catalog_dir,
    )

    assert not list(tmp_path.glob("coiner-lefranc-*"))


def test_google_search_keeps_only_allowlisted_lefranc_coin_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_CSE_ID", "test-engine")
    requested_urls: list[str] = []
    monkeypatch.setattr(
        "coiner.catalog_fallback._get_bytes",
        lambda url, **_kwargs: (
            requested_urls.append(url)
            or json.dumps(
                {
                    "items": [
                        {"link": "https://www.lefranc.net/monnaie,5-francs,340.html"},
                        {"link": "https://attacker.example/monnaie,coin,1.html"},
                    ]
                }
            ).encode()
        ),
    )

    urls = _google_lefranc_urls(
        CoinIdentity(country="France", denomination="5 francs", year=1960)
    )

    assert urls == ["https://www.lefranc.net/monnaie,5-francs,340.html"]
    assert len(requested_urls) == 1
    assert "key=test-key" in requested_urls[0]
    assert "1960" in requested_urls[0]


def test_lefranc_index_fallback_downloads_and_ingests_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("NUMISTA_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    monkeypatch.setattr(
        "coiner.catalog_fallback._google_lefranc_urls", lambda _identity: []
    )
    coin_html = b"""
    <html><head><title>France 5 francs Semeuse</title></head><body>
    <table><tr><th>Year</th><th>VF</th><th>XF</th></tr>
    <tr><td>1960</td><td>EUR 2,00</td><td>EUR 5,00</td></tr></table>
    </body></html>
    """
    requested_urls: list[str] = []

    def download(url: str, **_kwargs: object) -> bytes:
        requested_urls.append(url)
        if "/piece," in url:
            return (
                b'<a href="/monnaie,5-francs-semeuse,340.html">'
                b"5 francs Semeuse 1960</a>"
            )
        return coin_html

    monkeypatch.setattr("coiner.catalog_fallback._get_bytes", download)
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    index = CatalogIndex(tmp_path / "catalog.sqlite3")

    result = resolve_catalog_miss(
        CoinIdentity(country="France", denomination="5 francs", year=1960),
        catalog=index,
        catalog_dir=catalog_dir,
    )

    assert [(entry.condition, entry.price) for entry in result.entries] == [
        ("VF", 2),
        ("XF", 5),
    ]
    assert requested_urls == [
        "https://www.lefranc.net/piece,5-francs.html",
        "https://www.lefranc.net/monnaie,5-francs-semeuse,340.html",
    ]
    assert not list(tmp_path.glob("coiner-lefranc-*"))
