from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Sequence

from coiner.models import CatalogEntry


GRADE_ALIASES = {
    "g": "G",
    "good": "G",
    "vg": "VG",
    "very good": "VG",
    "tb": "VG",
    "tres beau": "VG",
    "très beau": "VG",
    "f": "F",
    "fine": "F",
    "b": "F",
    "beau": "F",
    "vf": "VF",
    "very fine": "VF",
    "ttb": "VF",
    "tres tres beau": "VF",
    "très très beau": "VF",
    "xf": "XF",
    "ef": "XF",
    "extremely fine": "XF",
    "superbe": "XF",
    "sup": "XF",
    "au": "AU",
    "about uncirculated": "AU",
    "spl": "AU",
    "splendide": "AU",
    "unc": "UNC",
    "uncirculated": "UNC",
    "ms": "UNC",
    "mint state": "UNC",
    "fdc": "UNC",
    "fleur de coin": "UNC",
}


def canonical_grade(condition: str) -> str | None:
    without_annotation = condition.split("(", maxsplit=1)[0]
    normalized = " ".join(without_annotation.casefold().strip().split())
    return GRADE_ALIASES.get(normalized)


@dataclass(frozen=True)
class PriceEvaluation:
    source: str
    currency: str
    price: float
    matched_conditions: tuple[str, ...]
    canonical_grade: str
    entries: tuple[CatalogEntry, ...]


def matching_grade_rank(entry: CatalogEntry, condition: str) -> int:
    if entry.condition.casefold().strip() == condition.casefold().strip():
        return 0
    expected_grade = canonical_grade(condition)
    if expected_grade and canonical_grade(entry.condition) == expected_grade:
        return 1
    return 2


def select_nearest_matches(
    entries: Sequence[CatalogEntry], condition: str, limit: int = 3
) -> list[CatalogEntry]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    ranked = sorted(
        entries,
        key=lambda entry: (
            matching_grade_rank(entry, condition),
            entry.source,
            entry.condition.casefold(),
            entry.currency,
        ),
    )

    selected: list[CatalogEntry] = []
    selected_ids: set[str] = set()
    selected_sources: set[str] = set()
    if ranked:
        selected.append(ranked[0])
        selected_ids.add(ranked[0].id)
        selected_sources.add(ranked[0].source)

    for source in sorted({entry.source for entry in ranked}):
        if source in selected_sources:
            continue
        best_for_source = next(entry for entry in ranked if entry.source == source)
        selected.append(best_for_source)
        selected_ids.add(best_for_source.id)
        selected_sources.add(source)
        if len(selected) == limit:
            return selected

    selected.extend(entry for entry in ranked if entry.id not in selected_ids)
    return selected[:limit]


def evaluate_catalog_prices(
    entries: Sequence[CatalogEntry], condition: str
) -> list[PriceEvaluation]:
    expected_grade = canonical_grade(condition)
    if expected_grade is None:
        return []

    groups: dict[tuple[str, str], list[CatalogEntry]] = defaultdict(list)
    for entry in entries:
        if canonical_grade(entry.condition) == expected_grade:
            groups[(entry.source, entry.currency)].append(entry)

    evaluations = []
    for (source, currency), matching_entries in sorted(groups.items()):
        evaluations.append(
            PriceEvaluation(
                source=source,
                currency=currency,
                price=float(median(entry.price for entry in matching_entries)),
                matched_conditions=tuple(
                    sorted({entry.condition for entry in matching_entries})
                ),
                canonical_grade=expected_grade,
                entries=tuple(matching_entries),
            )
        )
    return evaluations
