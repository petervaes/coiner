import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timezone, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from dotenv import load_dotenv

from coiner.catalog import CatalogIndex
from coiner.html_catalog_parser import (
    HTMLCatalogParseError,
    parse_coin_catalog_file,
)
from coiner.models import CatalogEntry, CoinIdentity

load_dotenv()

LEFRANC_HOST = "www.lefranc.net"
LEFRANC_MAX_CANDIDATE_PAGES = 8
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 20


class CatalogFallbackError(RuntimeError):
    pass


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, hosts: set[str]) -> None:
        super().__init__()
        self._hosts = hosts

    def redirect_request(
        self,
        request: Request,
        file: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> Request | None:
        if not _allowed_source_url(new_url, self._hosts):
            raise CatalogFallbackError(
                "The source redirected outside its permitted HTTPS hosts"
            )
        return super().redirect_request(
            request, file, code, message, headers, new_url
        )


@dataclass(frozen=True)
class FallbackResult:
    entries: tuple[CatalogEntry, ...]
    metadata: tuple[dict[str, object], ...]
    messages: tuple[str, ...]


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None


def _allowed_source_url(url: str, hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.casefold() in hosts
        and not parsed.username
        and not parsed.password
    )


def _get_bytes(
    url: str, *, hosts: set[str], headers: dict[str, str] | None = None
) -> bytes:
    if not _allowed_source_url(url, hosts):
        raise CatalogFallbackError("Refusing to request a URL outside the source allowlist")
    request_headers = {
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
        "User-Agent": "Coiner/0.1 (source-attributed coin catalog lookup)",
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    try:
        opener = build_opener(_AllowlistedRedirectHandler(hosts))
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            if not _allowed_source_url(final_url, hosts):
                raise CatalogFallbackError(
                    "The source redirected outside its permitted host"
                )
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_RESPONSE_BYTES:
                        raise CatalogFallbackError(
                            "Source response exceeds the 5 MB limit"
                        )
                except ValueError as exc:
                    raise CatalogFallbackError(
                        "Source returned an invalid Content-Length header"
                    ) from exc
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise CatalogFallbackError(
            f"Source returned HTTP {exc.code}; no retry or access-control bypass attempted"
        ) from exc
    except URLError as exc:
        raise CatalogFallbackError(f"Could not reach source: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CatalogFallbackError(
            f"Source request timed out after {HTTP_TIMEOUT_SECONDS} seconds"
        ) from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise CatalogFallbackError("Source response exceeds the 5 MB limit")
    return body


def _capture_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _slug(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def _persist_records(
    records: list[dict[str, object]],
    *,
    source: str,
    catalog_dir: Path,
    catalog: CatalogIndex,
) -> None:
    import_directory = catalog_dir / "imports"
    import_directory.mkdir(parents=True, exist_ok=True)
    identity = records[0]
    key = _slug(
        "-".join(
            str(identity.get(part, "unknown"))
            for part in ("source", "country", "denomination", "year")
        )
    )
    destination = import_directory / f"{key}-{source}.json"
    temp_path: Path | None = None
    previous_contents = destination.read_bytes() if destination.exists() else None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=import_directory,
            prefix=f".{uuid4().hex}-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            json.dump(records, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.replace(temp_path, destination)
        catalog.ingest(import_directory)
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        if previous_contents is None and destination.exists():
            destination.unlink()
        elif previous_contents is not None:
            destination.write_bytes(previous_contents)
        raise


def _persist_metadata(
    records: list[dict[str, object]],
    *,
    catalog_dir: Path,
    catalog: CatalogIndex,
) -> None:
    metadata_directory = catalog_dir / "imports"
    metadata_directory.mkdir(parents=True, exist_ok=True)
    filename = _slug(str(records[0]["id"])) + ".metadata.json"
    destination = metadata_directory / filename
    temp_path: Path | None = None
    previous_contents = destination.read_bytes() if destination.exists() else None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=metadata_directory,
            prefix=f".{uuid4().hex}-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            json.dump(records, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.replace(temp_path, destination)
        catalog.ingest(metadata_directory)
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        if previous_contents is None and destination.exists():
            destination.unlink()
        elif previous_contents is not None:
            destination.write_bytes(previous_contents)
        raise


def _google_lefranc_urls(identity: CoinIdentity) -> list[str]:
    api_key = os.environ.get("GOOGLE_CSE_API_KEY")
    search_engine_id = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not search_engine_id:
        return []
    query = (
        f"site:{LEFRANC_HOST}/monnaie {identity.country} "
        f'"{identity.denomination}"'
    )
    if identity.year is not None:
        query += f" {identity.year}"
    url = "https://www.googleapis.com/customsearch/v1?" + urlencode(
        {"key": api_key, "cx": search_engine_id, "q": query, "num": 5}
    )
    body = _get_bytes(url, hosts={"www.googleapis.com"})
    try:
        response = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CatalogFallbackError("Google Custom Search returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise CatalogFallbackError("Google Custom Search returned an unexpected response")
    if "error" in response:
        error = response["error"]
        detail = error.get("message") if isinstance(error, dict) else None
        raise CatalogFallbackError(
            f"Google Custom Search reported an error: {detail or 'unknown error'}"
        )
    items = response.get("items", [])
    if not isinstance(items, list):
        return []
    urls: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if (
            isinstance(link, str)
            and _allowed_source_url(link, {LEFRANC_HOST})
            and "/monnaie" in urlparse(link).path
        ):
            urls.append(link)
    return list(dict.fromkeys(urls))


def _lefranc_index_urls(identity: CoinIdentity) -> list[str]:
    denomination_slug = _slug(identity.denomination)
    if not denomination_slug:
        return []
    index_url = f"https://{LEFRANC_HOST}/piece,{denomination_slug}.html"
    body = _get_bytes(index_url, hosts={LEFRANC_HOST})
    parser = _LinkCollector()
    parser.feed(body.decode("utf-8", errors="replace"))
    candidates: list[tuple[int, str]] = []
    for href, label in parser.links:
        absolute_url = urljoin(index_url, href)
        if not _allowed_source_url(absolute_url, {LEFRANC_HOST}):
            continue
        if "/monnaie," not in urlparse(absolute_url).path:
            continue
        year_text = label
        has_year = bool(
            identity.year is not None
            and re.search(rf"(?<!\d){identity.year}(?!\d)", year_text)
        )
        candidates.append((0 if has_year else 1, absolute_url))
    candidates.sort()
    return list(dict.fromkeys(url for _, url in candidates))[
        :LEFRANC_MAX_CANDIDATE_PAGES
    ]


def _parse_lefranc_url(
    url: str,
    identity: CoinIdentity,
    *,
    catalog_dir: Path,
    catalog: CatalogIndex,
    capture_date: str,
) -> list[CatalogEntry]:
    with tempfile.TemporaryDirectory(prefix="coiner-lefranc-") as temp_dir:
        html_path = Path(temp_dir) / f"{uuid4().hex}.html"
        html_path.write_bytes(_get_bytes(url, hosts={LEFRANC_HOST}))
        records = parse_coin_catalog_file(
            html_path,
            source="lefranc",
            source_url=url,
            country=identity.country,
            denomination=identity.denomination,
            capture_date=capture_date,
            year=identity.year,
        )
    exact_year_records = [
        record for record in records if record.get("year") == identity.year
    ]
    if identity.year is None:
        exact_year_records = records
    if not exact_year_records:
        return []
    _persist_records(
        exact_year_records,
        source="lefranc",
        catalog_dir=catalog_dir,
        catalog=catalog,
    )
    return [
        entry
        for entry in catalog.search(
            identity.search_text(),
            limit=100,
            country=identity.country,
            denomination=identity.denomination,
            year=identity.year,
        )
        if entry.source == "lefranc"
        and (identity.year is None or entry.year == identity.year)
    ]


def _text_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("en", "name", "value"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _api_year(item: dict[str, object]) -> int | None:
    for key in ("year", "date", "min_year", "year_from", "start_year"):
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", value)
            if match:
                return int(match.group(1))
    return None


def _numista_metadata(
    item: dict[str, object],
    identity: CoinIdentity,
    *,
    capture_date: str,
) -> dict[str, object] | None:
    numista_id = item.get("id")
    if numista_id is None:
        return None
    title = (
        _text_value(item.get("title"))
        or _text_value(item.get("name"))
        or f"{identity.country} {identity.denomination}"
    )
    year = _api_year(item)
    if identity.year is not None and year is not None and year != identity.year:
        minimum = item.get("min_year") or item.get("year_from")
        maximum = item.get("max_year") or item.get("year_to")
        if not (
            isinstance(minimum, int)
            and isinstance(maximum, int)
            and minimum <= identity.year <= maximum
        ):
            return None
    url = f"https://en.numista.com/catalogue/pieces{numista_id}.html"
    return {
        "id": f"numista-type-{numista_id}",
        "source": "numista",
        "source_url": url,
        "country": identity.country,
        "denomination": identity.denomination,
        "title": title,
        "year": year or identity.year,
        "ruler_or_issuer": _text_value(item.get("issuer")),
        "description": _text_value(item.get("description")),
        "catalog_reference": _text_value(item.get("reference")),
        "capture_date": capture_date,
        "notes": (
            "Coin type metadata imported from the Numista API. The API response "
            "contained no verified grade-price table."
        ),
    }


def _numista_api_records(
    identity: CoinIdentity, *, capture_date: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    api_key = os.environ.get("NUMISTA_API_KEY")
    if not api_key:
        return [], []
    query = identity.search_text()
    parameters = {"q": query, "lang": "en", "category": "coin"}
    url = "https://api.numista.com/api/v3/types?" + urlencode(parameters)
    with tempfile.TemporaryDirectory(prefix="coiner-numista-") as temp_dir:
        response_path = Path(temp_dir) / f"{uuid4().hex}.json"
        response_path.write_bytes(
            _get_bytes(
                url,
                hosts={"api.numista.com"},
                headers={"Numista-API-Key": api_key, "Accept": "application/json"},
            )
        )
        try:
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CatalogFallbackError("Numista API returned invalid JSON") from exc
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        items = response.get("types") or response.get("items") or response.get("results")
    else:
        items = None
    if not isinstance(items, list):
        return [], []
    metadata: list[dict[str, object]] = []
    price_records: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _numista_metadata(item, identity, capture_date=capture_date)
        if record is None:
            continue
        metadata.append(record)
        prices = item.get("prices")
        if not isinstance(prices, dict) or not prices:
            continue
        normalized_prices = {
            str(grade): value
            for grade, value in prices.items()
            if isinstance(grade, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
        currency = item.get("currency")
        if (
            not normalized_prices
            or not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
        ):
            continue
        price_records.append(
            {
                **record,
                "id": str(record["id"]) + "-prices",
                "prices": normalized_prices,
                "currency": currency.upper(),
                "as_of": capture_date,
            }
        )
    return metadata, price_records


def resolve_catalog_miss(
    identity: CoinIdentity,
    *,
    catalog: CatalogIndex,
    catalog_dir: Path,
) -> FallbackResult:
    capture_date = _capture_date()
    messages: list[str] = []
    metadata: list[dict[str, object]] = []
    entries: list[CatalogEntry] = []

    if not os.environ.get("NUMISTA_API_KEY"):
        messages.append("Numista API skipped: configure NUMISTA_API_KEY to enable it.")
    if not (
        os.environ.get("GOOGLE_CSE_API_KEY")
        and os.environ.get("GOOGLE_CSE_ID")
    ):
        messages.append(
            "Google search skipped: configure GOOGLE_CSE_API_KEY and "
            "GOOGLE_CSE_ID; the LeFranc index fallback will still be tried."
        )

    try:
        api_metadata, api_prices = _numista_api_records(
            identity, capture_date=capture_date
        )
        if api_metadata:
            metadata.extend(api_metadata)
            _persist_metadata(
                api_metadata, catalog_dir=catalog_dir, catalog=catalog
            )
        if api_prices:
            _persist_records(
                api_prices,
                source="numista",
                catalog_dir=catalog_dir,
                catalog=catalog,
            )
        entries.extend(
            entry
            for entry in catalog.search(
                identity.search_text(),
                limit=100,
                country=identity.country,
                denomination=identity.denomination,
                year=identity.year,
            )
            if entry.source == "numista"
            and (identity.year is None or entry.year == identity.year)
        )
        if api_metadata and not api_prices:
            messages.append(
                "Numista API returned coin metadata but no grade-price table; "
                "no Numista price was invented."
            )
    except CatalogFallbackError as exc:
        messages.append(f"Numista: {exc}")

    lefranc_urls: list[str] = []
    try:
        lefranc_urls.extend(_google_lefranc_urls(identity))
    except CatalogFallbackError as exc:
        messages.append(f"Google Custom Search: {exc}")

    for url in dict.fromkeys(lefranc_urls):
        try:
            page_entries = _parse_lefranc_url(
                url,
                identity,
                catalog_dir=catalog_dir,
                catalog=catalog,
                capture_date=capture_date,
            )
        except (CatalogFallbackError, HTMLCatalogParseError) as exc:
            messages.append(f"LeFranc page {url}: {exc}")
            continue
        if page_entries:
            entries.extend(page_entries)
            break

    if not any(entry.source == "lefranc" for entry in entries):
        try:
            index_urls = _lefranc_index_urls(identity)
        except CatalogFallbackError as exc:
            messages.append(f"LeFranc index: {exc}")
            index_urls = []
        for url in index_urls:
            try:
                page_entries = _parse_lefranc_url(
                    url,
                    identity,
                    catalog_dir=catalog_dir,
                    catalog=catalog,
                    capture_date=capture_date,
                )
            except (CatalogFallbackError, HTMLCatalogParseError) as exc:
                messages.append(f"LeFranc page {url}: {exc}")
                continue
            if page_entries:
                entries.extend(page_entries)
                break

    unique_entries = {entry.id: entry for entry in entries}
    return FallbackResult(
        entries=tuple(unique_entries.values()),
        metadata=tuple(metadata),
        messages=tuple(messages),
    )
