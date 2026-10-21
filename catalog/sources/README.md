# Catalog source data

The CLI indexes JSON Lines (`.jsonl`) files in this directory. Each line is one
document with a source-backed catalog price. Keep the original source URL,
currency, condition, and date with every price; do not enter an AI-generated
estimate as a catalog value.

Required fields:

```json
{"id":"unique-id","title":"Coin catalog entry","country":"France","denomination":"1 franc","year":1900,"source":"numista","source_url":"https://example.org/coin","price":12.5,"currency":"EUR","condition":"VF","as_of":"2026-10-21"}
```

`source` must be `lefranc` or `numista`. `year` and these fields are optional:
`mint`, `ruler_or_issuer`, `catalog_reference`, and `notes`. Replace the example
URL and values with verified data before indexing; this repository does not ship
catalog prices.

Install the CLI from the repository root:

```powershell
python -m pip install -e .
```

Then import catalog data and run the CLI:

```powershell
python -m coiner ingest --source-dir catalog/sources --database data/coiner.sqlite3
python -m coiner analyze .\coin.jpg --database data/coiner.sqlite3
python -m coiner search "France 1 franc 1900" --database data/coiner.sqlite3
```

Photo identification sends the image to the OpenAI API. Set `OPENAI_API_KEY`
in a local `.env` file first. Start by copying the tracked example:

```powershell
Copy-Item .env.example .env
```

Then replace the placeholder `OPENAI_API_KEY` in `.env` with your API key.
Never commit `.env`; it is ignored by Git. `OPENAI_MODEL` can be changed there
if needed.

The local retrieval index uses SQLite FTS5. Live LeFranc/Numista fetching is
not enabled: populate the JSONL files only from data you are permitted to use,
or connect an authorized source API/export before relying on catalog prices.
