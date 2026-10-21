from dataclasses import dataclass
from statistics import median
from typing import Sequence

from coiner.models import CatalogEntry


@dataclass(frozen=True)
class PriceEvaluation:
    price: float | None
    currency: str | None
    supporting_entries: tuple[CatalogEntry, ...]
    explanation: str


def evaluate_catalog_prices(
    entries: Sequence[CatalogEntry], condition: str
) -> PriceEvaluation:
    same_grade = [
        entry for entry in entries if entry.condition.casefold() == condition.casefold()
    ]
    euro_prices = [entry for entry in same_grade if entry.currency == "EUR"]
    if euro_prices:
        price = float(median(entry.price for entry in euro_prices))
        explanation = (
            f"Mediaan van {len(euro_prices)} EUR-catalogusprijs"
            f"{'zen' if len(euro_prices) != 1 else ''} met exact dezelfde conditie "
            f"({condition}); waarden zijn bron-snapshots, geen live marktfeed."
        )
        return PriceEvaluation(
            price=price,
            currency="EUR",
            supporting_entries=tuple(euro_prices),
            explanation=explanation,
        )

    if same_grade:
        currencies = sorted({entry.currency for entry in same_grade})
        return PriceEvaluation(
            price=None,
            currency=None,
            supporting_entries=tuple(same_grade),
            explanation=(
                f"Geen EUR-prijzen beschikbaar voor conditie {condition}. "
                f"Beschikbare valuta ({', '.join(currencies)}) zijn niet omgerekend."
            ),
        )

    return PriceEvaluation(
        price=None,
        currency=None,
        supporting_entries=(),
        explanation=(
            f"Geen catalogusprijs gevonden met exact dezelfde conditie ({condition}); "
            "condities zijn niet automatisch omgerekend."
        ),
    )
