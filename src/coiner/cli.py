import argparse
import json
import sys
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from coiner.catalog import CatalogIndex
from coiner.models import CoinIdentity
from coiner.vision import VisionError, identify_coin

DEFAULT_DATABASE = Path("data/coiner.sqlite3")
DEFAULT_SOURCE_DIR = Path("catalog")


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _exact_catalog_matches(
    catalog: CatalogIndex, identity: CoinIdentity
) -> list[dict[str, object]]:
    candidates = catalog.search(
        identity.search_text(),
        limit=25,
        country=identity.country,
        denomination=identity.denomination,
        year=identity.year,
    )
    matches = [
        entry
        for entry in candidates
        if _normalize(entry.country) == _normalize(identity.country)
        and _normalize(entry.denomination) == _normalize(identity.denomination)
        and (identity.year is None or entry.year == identity.year)
    ]
    return [entry.to_dict() for entry in matches]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coiner",
        description="Identify a coin from a photo and search source-backed catalog prices.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Index catalog JSONL files")
    ingest.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    ingest.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    ingest.add_argument("--rebuild", action="store_true", help="Clear and rebuild the index")

    analyze = commands.add_parser(
        "analyze", help="Identify a coin photo and look up matching catalog prices"
    )
    analyze.add_argument("image", type=Path)
    analyze.add_argument("--database", type=Path, default=DEFAULT_DATABASE)

    search = commands.add_parser("search", help="Search the local catalog index")
    search.add_argument("query")
    search.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    search.add_argument("--limit", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    try:
        catalog = CatalogIndex(args.database)
        if args.command == "ingest":
            count = catalog.ingest(args.source_dir, clear=args.rebuild)
            print(json.dumps({"indexed_entries": count, "database": str(args.database)}))
            return
        if args.command == "search":
            entries = catalog.search(args.query, limit=args.limit)
            print(
                json.dumps(
                    [entry.to_dict() for entry in entries],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        identity = identify_coin(args.image)
        matches = _exact_catalog_matches(catalog, identity)
        output = {
            "identification": asdict(identity),
            "catalog_prices": matches,
            "message": (
                None
                if matches
                else "No exact catalog price found; no price has been inferred."
            ),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (FileNotFoundError, ValueError, VisionError) as exc:
        print(f"coiner: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
