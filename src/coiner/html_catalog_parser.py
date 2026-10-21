import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from coiner.valuation import canonical_grade


class HTMLCatalogParseError(ValueError):
    pass


class _Cell:
    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


class _Table:
    def __init__(self) -> None:
        self.rows: list[list[_Cell]] = []


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self._table: _Table | None = None
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._in_title = False
        self._heading_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in {"h1", "h2"}:
            self._heading_depth += 1
        elif tag == "table" and self._table is None:
            self._table = _Table()
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = _Cell(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2"} and self._heading_depth:
            self._heading_depth -= 1
        elif tag in {"th", "td"} and self._cell is not None:
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._table is not None and self._row:
                self._table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.parts.append(data)
        if self._in_title:
            self.title_parts.append(data)
        if self._heading_depth:
            self.heading_parts.append(data)


_YEAR = re.compile(r"(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)")
_NUMBER = re.compile(r"(?<!\w)(\d[\d\s.,'’]*\d|\d)(?!\w)")
_CURRENCIES = (
    ("EUR", re.compile(r"(?:€|\bEUR\b)", re.IGNORECASE)),
    ("USD", re.compile(r"(?:\$|\bUSD\b)", re.IGNORECASE)),
    ("GBP", re.compile(r"(?:£|\bGBP\b)", re.IGNORECASE)),
    ("CHF", re.compile(r"\bCHF\b", re.IGNORECASE)),
)
_MINTAGE_HEADERS = {"mintage", "mintages", "tirage", "frappe", "auflage"}
_YEAR_HEADERS = {"year", "date", "annee", "jahr", "año"}
_FREQUENCY_HEADERS = {"frequency", "frequence", "frequencies", "rarete"}
_GRADE_HEADERS = {"grade", "grading", "condition", "quality", "qualite", "etat"}
_PRICE_HEADERS = {"price", "prices", "prix", "cote", "value", "valeur", "quotation"}


def _plain_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(char for char in value if not unicodedata.combining(char)).split()
    )


def _normalize_number(number: str) -> float | None:
    compact = re.sub(r"[\s'’]", "", number)
    if not compact:
        return None
    comma = compact.rfind(",")
    dot = compact.rfind(".")
    decimal_separator: str | None = None
    if comma >= 0 and dot >= 0:
        decimal_separator = "," if comma > dot else "."
    elif comma >= 0:
        trailing = len(compact) - comma - 1
        decimal_separator = "," if trailing in {1, 2} else None
    elif dot >= 0:
        trailing = len(compact) - dot - 1
        decimal_separator = "." if trailing in {1, 2} else None

    if decimal_separator:
        grouping_separator = "." if decimal_separator == "," else ","
        compact = compact.replace(grouping_separator, "")
        compact = compact.replace(decimal_separator, ".")
    else:
        compact = compact.replace(",", "").replace(".", "")
    try:
        return float(compact)
    except ValueError:
        return None


def _parse_price(value: str, default_currency: str) -> tuple[str, float] | None:
    currency = default_currency
    for code, pattern in _CURRENCIES:
        if pattern.search(value):
            currency = code
            break
    match = _NUMBER.search(value)
    if not match:
        return None
    price = _normalize_number(match.group(1))
    return (currency, price) if price is not None else None


def _parse_integer(value: str) -> int | None:
    match = _NUMBER.search(value)
    if not match:
        return None
    number = _normalize_number(match.group(1))
    if number is None or not number.is_integer():
        return None
    return int(number)


def _header_columns(
    rows: Sequence[Sequence[_Cell]],
) -> tuple[int, dict[int, str], dict[int, str]] | None:
    best: tuple[int, dict[int, str], dict[int, str]] | None = None
    for header_index, row in enumerate(rows[:8]):
        grades: dict[int, str] = {}
        metadata: dict[int, str] = {}
        for column_index, cell in enumerate(row):
            grade_label = re.sub(r"\s*\([^)]*\)\s*$", "", cell.text).strip()
            grade = canonical_grade(grade_label)
            if grade:
                grades[column_index] = cell.text
            header = _plain_text(cell.text)
            if header in _YEAR_HEADERS:
                metadata[column_index] = "year"
            elif header in _MINTAGE_HEADERS:
                metadata[column_index] = "mintage"
            elif header in _FREQUENCY_HEADERS or "frequenc" in header:
                metadata[column_index] = "frequency"
        has_header_cells = any(cell.tag == "th" for cell in row)
        if grades and (
            has_header_cells or metadata or len(grades) > 1
        ) and (best is None or len(grades) > len(best[1])):
            best = (header_index, grades, metadata)
    return best


def _vertical_header_columns(
    rows: Sequence[Sequence[_Cell]],
) -> tuple[int, int, int, dict[int, str]] | None:
    for header_index, row in enumerate(rows[:8]):
        grade_index: int | None = None
        price_index: int | None = None
        metadata: dict[int, str] = {}
        for column_index, cell in enumerate(row):
            header = _plain_text(cell.text)
            if header in _GRADE_HEADERS:
                grade_index = column_index
            elif header in _PRICE_HEADERS or any(
                word in header for word in ("price", "prix", "cote", "valeur")
            ):
                price_index = column_index
            if header in _YEAR_HEADERS:
                metadata[column_index] = "year"
            elif header in _MINTAGE_HEADERS:
                metadata[column_index] = "mintage"
            elif header in _FREQUENCY_HEADERS or "frequenc" in header:
                metadata[column_index] = "frequency"
        if grade_index is not None and price_index is not None:
            return header_index, grade_index, price_index, metadata
    return None


def _page_title(parser: _TableParser, fallback: str) -> str:
    title = " ".join(" ".join(parser.title_parts).split())
    if not title:
        title = " ".join(" ".join(parser.heading_parts).split())
    return title or fallback


def parse_coin_catalog_html(
    html: str,
    *,
    source: str,
    source_url: str,
    country: str,
    denomination: str,
    capture_date: str | None = None,
    currency: str = "EUR",
    year: int | None = None,
) -> list[dict[str, object]]:
    """Parse a local coin catalog HTML snapshot into grouped catalog records.

    The parser supports tables with grade labels in column headers and one coin
    variant per row. It deliberately performs no network requests.
    """
    normalized_source = source.casefold().strip()
    if normalized_source not in {"numista", "lefranc"}:
        raise HTMLCatalogParseError("source must be 'numista' or 'lefranc'")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise HTMLCatalogParseError("source_url must be an HTTPS URL")
    if not country.strip() or not denomination.strip():
        raise HTMLCatalogParseError("country and denomination are required")
    capture_date = capture_date or date.today().isoformat()
    try:
        date.fromisoformat(capture_date)
    except ValueError as exc:
        raise HTMLCatalogParseError(
            "capture_date must be an ISO date (YYYY-MM-DD)"
        ) from exc
    normalized_currency = currency.upper()
    if len(normalized_currency) != 3 or not normalized_currency.isalpha():
        raise HTMLCatalogParseError("currency must be a three-letter code")

    parser = _TableParser()
    parser.feed(html)
    parser.close()
    default_title = f"{country.strip()} {denomination.strip()}"
    title = _page_title(parser, default_title)
    grouped_records: list[dict[str, object]] = []
    row_number = 0
    page_fingerprint = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:8]

    for table in parser.tables:
        header = _header_columns(table.rows)
        if header is None:
            vertical_header = _vertical_header_columns(table.rows)
            if vertical_header is None:
                continue
            header_index, grade_index, price_index, metadata_columns = vertical_header
            for row in table.rows[header_index + 1 :]:
                values = [cell.text for cell in row]
                if max(grade_index, price_index) >= len(values):
                    continue
                grade_label = values[grade_index]
                if canonical_grade(grade_label) is None:
                    continue
                parsed_price = _parse_price(values[price_index], normalized_currency)
                if parsed_price is None:
                    continue
                row_year = year
                mintage: int | None = None
                frequency: float | None = None
                for index, kind in metadata_columns.items():
                    if index >= len(values):
                        continue
                    if kind == "year":
                        year_match = _YEAR.search(values[index])
                        if year_match:
                            row_year = int(year_match.group(1))
                    elif kind == "mintage":
                        mintage = _parse_integer(values[index])
                    elif kind == "frequency":
                        parsed_frequency = _parse_price(
                            values[index], normalized_currency
                        )
                        if parsed_frequency:
                            frequency = parsed_frequency[1]
                if row_year is None:
                    for value in values:
                        year_match = _YEAR.search(value)
                        if year_match:
                            row_year = int(year_match.group(1))
                            break

                row_number += 1
                price_currency, price = parsed_price
                slug = re.sub(
                    r"[^a-z0-9]+",
                    "-",
                    f"{normalized_source}-{country}-{denomination}-{row_year or 'unknown'}-{page_fingerprint}-{row_number}-{price_currency}",
                    flags=re.IGNORECASE,
                ).strip("-").lower()
                record: dict[str, object] = {
                    "id": slug,
                    "title": title,
                    "country": country.strip(),
                    "denomination": denomination.strip(),
                    "source": normalized_source,
                    "source_url": source_url,
                    "prices": {grade_label: price},
                    "currency": price_currency,
                    "as_of": capture_date,
                    "year": row_year,
                    "notes": (
                        f"Parsed from a local HTML snapshot captured on {capture_date}; "
                        "the source quotation date was not inferred."
                    ),
                }
                if mintage is not None:
                    record["mintage"] = mintage
                if frequency is not None:
                    record["frequency_percent"] = frequency
                grouped_records.append(record)
            continue
        header_index, grade_columns, metadata_columns = header
        for row in table.rows[header_index + 1 :]:
            if not row:
                continue
            values = [cell.text for cell in row]
            row_year = year
            mintage: int | None = None
            frequency: float | None = None
            for index, kind in metadata_columns.items():
                if index >= len(values):
                    continue
                value = values[index]
                if kind == "year":
                    year_match = _YEAR.search(value)
                    if year_match:
                        row_year = int(year_match.group(1))
                elif kind == "mintage":
                    mintage = _parse_integer(value)
                elif kind == "frequency":
                    parsed_frequency = _parse_price(value, normalized_currency)
                    if parsed_frequency:
                        frequency = parsed_frequency[1]

            if row_year is None:
                for value in values:
                    year_match = _YEAR.search(value)
                    if year_match:
                        row_year = int(year_match.group(1))
                        break

            prices_by_currency: dict[str, dict[str, float]] = defaultdict(dict)
            for column_index, grade in grade_columns.items():
                if column_index >= len(values):
                    continue
                parsed_price = _parse_price(values[column_index], normalized_currency)
                if parsed_price:
                    price_currency, price = parsed_price
                    prices_by_currency[price_currency][grade] = price
            if not prices_by_currency:
                continue

            row_number += 1
            for price_currency, prices in prices_by_currency.items():
                slug = re.sub(
                    r"[^a-z0-9]+",
                    "-",
                    f"{normalized_source}-{country}-{denomination}-{row_year or 'unknown'}-{page_fingerprint}-{row_number}-{price_currency}",
                    flags=re.IGNORECASE,
                ).strip("-").lower()
                notes = (
                    f"Parsed from a local HTML snapshot captured on {capture_date}; "
                    "the source quotation date was not inferred."
                )
                record: dict[str, object] = {
                    "id": slug,
                    "title": title,
                    "country": country.strip(),
                    "denomination": denomination.strip(),
                    "source": normalized_source,
                    "source_url": source_url,
                    "prices": prices,
                    "currency": price_currency,
                    "as_of": capture_date,
                    "year": row_year,
                    "notes": notes,
                }
                if mintage is not None:
                    record["mintage"] = mintage
                if frequency is not None:
                    record["frequency_percent"] = frequency
                grouped_records.append(record)

    if not grouped_records:
        raise HTMLCatalogParseError(
            "No grade-price table found. Expected a table with recognized grade "
            "columns and at least one numeric price."
        )
    return grouped_records


def parse_coin_catalog_file(
    html_path: Path,
    *,
    source: str,
    source_url: str,
    country: str,
    denomination: str,
    capture_date: str | None = None,
    currency: str = "EUR",
    year: int | None = None,
) -> list[dict[str, object]]:
    try:
        html = html_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTMLCatalogParseError(
            f"{html_path} is not UTF-8 HTML; convert it to UTF-8 before parsing"
        ) from exc
    return parse_coin_catalog_html(
        html,
        source=source,
        source_url=source_url,
        country=country,
        denomination=denomination,
        capture_date=capture_date,
        currency=currency,
        year=year,
    )
