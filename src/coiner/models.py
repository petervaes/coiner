from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite
from urllib.parse import urlparse


@dataclass(frozen=True)
class CoinIdentity:
    country: str
    denomination: str
    year: int | None = None
    mint: str | None = None
    ruler_or_issuer: str | None = None
    description: str | None = None

    def search_text(self) -> str:
        return " ".join(
            value
            for value in (
                self.country,
                self.denomination,
                str(self.year) if self.year is not None else None,
                self.mint,
                self.ruler_or_issuer,
                self.description,
            )
            if value
        )


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    title: str
    country: str
    denomination: str
    source: str
    source_url: str
    price: float
    currency: str
    condition: str
    as_of: str
    year: int | None = None
    mint: str | None = None
    ruler_or_issuer: str | None = None
    catalog_reference: str | None = None
    notes: str | None = None
    mint_mark: str | None = None
    mintage: int | None = None
    frequency_percent: float | None = None
    related_source_url: str | None = None
    collection_grade: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CatalogEntry":
        required = (
            "id",
            "title",
            "country",
            "denomination",
            "source",
            "source_url",
            "price",
            "currency",
            "condition",
            "as_of",
        )
        missing = [field for field in required if field not in data]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        string_fields = (
            "id",
            "title",
            "country",
            "denomination",
            "source",
            "source_url",
            "currency",
            "condition",
            "as_of",
        )
        for field in string_fields:
            if not isinstance(data[field], str) or not data[field].strip():
                raise ValueError(f"{field} must be a non-empty string")

        source = str(data["source"]).lower()
        if source not in {"lefranc", "numista"}:
            raise ValueError("source must be 'lefranc' or 'numista'")

        parsed_url = urlparse(str(data["source_url"]))
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("source_url must be an HTTPS URL")

        currency = str(data["currency"]).upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")

        if isinstance(data["price"], bool):
            raise ValueError("price must be a number")
        try:
            price = float(data["price"])
        except (TypeError, ValueError) as exc:
            raise ValueError("price must be a number") from exc
        if not isfinite(price) or price < 0:
            raise ValueError("price must be finite and cannot be negative")

        as_of = str(data["as_of"])
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO date (YYYY-MM-DD)") from exc

        year_value = data.get("year")
        if year_value is not None and (
            not isinstance(year_value, int) or isinstance(year_value, bool)
        ):
            raise ValueError("year must be an integer or null")

        optional_fields = (
            "mint",
            "ruler_or_issuer",
            "catalog_reference",
            "notes",
            "mint_mark",
            "collection_grade",
        )
        optional_values: dict[str, str | None] = {}
        for field in optional_fields:
            value = data.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be a string or null")
            optional_values[field] = value

        mintage_value = data.get("mintage")
        if mintage_value is not None and (
            not isinstance(mintage_value, int)
            or isinstance(mintage_value, bool)
            or mintage_value < 0
        ):
            raise ValueError("mintage must be a non-negative integer or null")

        frequency_value = data.get("frequency_percent")
        if frequency_value is not None:
            if isinstance(frequency_value, bool):
                raise ValueError("frequency_percent must be a number from 0 to 100")
            try:
                frequency_value = float(frequency_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "frequency_percent must be a number from 0 to 100"
                ) from exc
            if not isfinite(frequency_value) or not 0 <= frequency_value <= 100:
                raise ValueError("frequency_percent must be a number from 0 to 100")

        related_source_url = data.get("related_source_url")
        if related_source_url is not None:
            if not isinstance(related_source_url, str) or not related_source_url.strip():
                raise ValueError("related_source_url must be a non-empty HTTPS URL")
            parsed_related_url = urlparse(related_source_url)
            if parsed_related_url.scheme != "https" or not parsed_related_url.netloc:
                raise ValueError("related_source_url must be an HTTPS URL")

        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            country=str(data["country"]),
            denomination=str(data["denomination"]),
            source=source,
            source_url=str(data["source_url"]),
            price=price,
            currency=currency,
            condition=str(data["condition"]),
            as_of=as_of,
            year=year_value,
            mint=optional_values["mint"],
            ruler_or_issuer=optional_values["ruler_or_issuer"],
            catalog_reference=optional_values["catalog_reference"],
            notes=optional_values["notes"],
            mint_mark=optional_values["mint_mark"],
            mintage=mintage_value,
            frequency_percent=frequency_value,
            related_source_url=related_source_url,
            collection_grade=optional_values["collection_grade"],
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def searchable_text(self) -> str:
        return " ".join(
            value
            for value in (
                self.title,
                self.country,
                self.denomination,
                str(self.year) if self.year is not None else None,
                self.mint,
                self.mint_mark,
                self.ruler_or_issuer,
                self.catalog_reference,
                self.collection_grade,
                self.condition,
                str(self.mintage) if self.mintage is not None else None,
                f"{self.frequency_percent:g}%"
                if self.frequency_percent is not None
                else None,
                self.notes,
            )
            if value
        )
