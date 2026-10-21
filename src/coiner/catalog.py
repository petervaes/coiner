import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from coiner.models import CatalogEntry


class CatalogIndex:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS coin_entries (
                    id TEXT PRIMARY KEY,
                    entry_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS coin_entries_fts
                USING fts5(id UNINDEXED, title, content, tokenize='unicode61')
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ingest(self, source_dir: Path, clear: bool = False) -> int:
        files = sorted((*source_dir.rglob("*.jsonl"), *source_dir.rglob("*.json")))
        if not files:
            raise FileNotFoundError(f"No JSON or JSONL catalog files found in {source_dir}")

        entries: list[CatalogEntry] = []
        for path in files:
            try:
                if path.suffix.lower() == ".json":
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        raise ValueError("JSON catalog must contain an array of entries")
                    for index, item in enumerate(data, start=1):
                        entries.extend(
                            self._parse_catalog_record(item, f"{path}:{index}")
                        )
                else:
                    with path.open(encoding="utf-8") as source_file:
                        for line_number, line in enumerate(source_file, start=1):
                            if not line.strip():
                                continue
                            item = json.loads(line)
                            entries.extend(
                                self._parse_catalog_record(item, f"{path}:{line_number}")
                            )
            except (json.JSONDecodeError, ValueError) as exc:
                if isinstance(exc, ValueError) and str(exc).startswith(str(path)):
                    raise
                raise ValueError(f"{path}: {exc}") from exc

        with self._connect() as connection:
            if clear:
                connection.execute("DELETE FROM coin_entries")
                connection.execute("DELETE FROM coin_entries_fts")
            for entry in entries:
                connection.execute(
                    "DELETE FROM coin_entries_fts WHERE id = ?", (entry.id,)
                )
                connection.execute(
                    """
                    INSERT INTO coin_entries (id, entry_json)
                    VALUES (?, ?)
                    ON CONFLICT(id) DO UPDATE SET entry_json = excluded.entry_json
                    """,
                    (entry.id, json.dumps(entry.to_dict(), ensure_ascii=False)),
                )
                connection.execute(
                    "INSERT INTO coin_entries_fts (id, title, content) VALUES (?, ?, ?)",
                    (entry.id, entry.title, entry.searchable_text()),
                )
        return len(entries)

    @staticmethod
    def _parse_catalog_record(data: object, location: str) -> list[CatalogEntry]:
        if not isinstance(data, dict):
            raise ValueError(f"{location}: entry must be a JSON object")
        prices = data.get("prices")
        if prices is None:
            try:
                return [CatalogEntry.from_dict(data)]
            except ValueError as exc:
                raise ValueError(f"{location}: {exc}") from exc
        if not isinstance(prices, dict) or not prices:
            raise ValueError(f"{location}: prices must be a non-empty grade-to-price object")

        base = {key: value for key, value in data.items() if key != "prices"}
        entries: list[CatalogEntry] = []
        for condition, price in prices.items():
            if not isinstance(condition, str) or not condition.strip():
                raise ValueError(f"{location}: each price grade must be a non-empty string")
            record = {
                **base,
                "id": f"{base.get('id', '')}-{condition.casefold().replace(' ', '-')}",
                "condition": condition,
                "price": price,
            }
            try:
                entries.append(CatalogEntry.from_dict(record))
            except ValueError as exc:
                raise ValueError(f"{location}, grade {condition}: {exc}") from exc
        return entries

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        country: str | None = None,
        denomination: str | None = None,
        year: int | None = None,
    ) -> list[CatalogEntry]:
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not terms:
            return []
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        match_expression = " OR ".join(f'"{term}"' for term in terms)
        filters = ["coin_entries_fts MATCH ?"]
        parameters: list[object] = [match_expression]
        if country is not None:
            filters.append("lower(json_extract(entry_json, '$.country')) = lower(?)")
            parameters.append(country)
        if denomination is not None:
            filters.append(
                "lower(json_extract(entry_json, '$.denomination')) = lower(?)"
            )
            parameters.append(denomination)
        if year is not None:
            filters.append("json_extract(entry_json, '$.year') = ?")
            parameters.append(year)
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT coin_entries.entry_json
                FROM coin_entries_fts
                JOIN coin_entries USING (id)
                WHERE {' AND '.join(filters)}
                ORDER BY bm25(coin_entries_fts), coin_entries.id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [CatalogEntry.from_dict(json.loads(row["entry_json"])) for row in rows]
