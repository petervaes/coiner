import json
import re
import sqlite3
from pathlib import Path

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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def ingest(self, source_dir: Path, clear: bool = False) -> int:
        files = sorted(source_dir.rglob("*.jsonl"))
        if not files:
            raise FileNotFoundError(f"No JSONL catalog files found in {source_dir}")

        entries: list[CatalogEntry] = []
        for path in files:
            with path.open(encoding="utf-8") as source_file:
                for line_number, line in enumerate(source_file, start=1):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if not isinstance(data, dict):
                            raise ValueError("entry must be a JSON object")
                        entries.append(CatalogEntry.from_dict(data))
                    except (json.JSONDecodeError, ValueError) as exc:
                        raise ValueError(f"{path}:{line_number}: {exc}") from exc

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

    def search(self, query: str, limit: int = 5) -> list[CatalogEntry]:
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not terms:
            return []
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        match_expression = " OR ".join(f'"{term}"' for term in terms)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT coin_entries.entry_json
                FROM coin_entries_fts
                JOIN coin_entries USING (id)
                WHERE coin_entries_fts MATCH ?
                ORDER BY bm25(coin_entries_fts), coin_entries.id
                LIMIT ?
                """,
                (match_expression, limit),
            ).fetchall()
        return [CatalogEntry.from_dict(json.loads(row["entry_json"])) for row in rows]
