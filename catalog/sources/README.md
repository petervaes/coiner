# Catalog source data

The CLI indexes JSON arrays (`.json`) and JSON Lines (`.jsonl`) files in the
catalog directory. JSONL files contain one source-backed price per line. A JSON
record can also group prices by grade using a `prices` object, which the index
expands into individual grade-specific records. Keep the original source URL,
currency, condition, and date with every price; do not enter an AI-generated
estimate as a catalog value.

Required fields:

```json
{"id":"unique-id","title":"Coin catalog entry","country":"France","denomination":"1 franc","year":1900,"source":"numista","source_url":"https://example.org/coin","price":12.5,"currency":"EUR","condition":"VF","as_of":"2026-10-21"}
```

`source` must be `lefranc` or `numista`. `year` and these fields are optional:
`mint`, `ruler_or_issuer`, `catalog_reference`, and `notes`. Replace the example
URL and values with verified data before indexing.

The Numista 1 franc Morlon table provided for this project is stored in
[`../catalog.json`](../catalog.json). It includes the listed 1931-1941 variants,
grade prices, mintages, frequencies, and associated LeFranc references. The
1935 prices are aligned to VF, XF, and AU as shown by the supplied table's
column positions. LeFranc's values for the series are stored in
[`../lefranc_1_franc_morlon.json`](../lefranc_1_franc_morlon.json), retaining
its own grade scale and EUR/USD values. The source page does not state a quote
date; the records note the page capture date instead. These are snapshots, not
claims that the source price lists are current.

From the repository root:

```powershell
python -m pip install -e .
```

Then import catalog data and run the CLI:

```powershell
python -m coiner ingest --source-dir catalog --database data/coiner.sqlite3
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
not enabled: populate the catalog files only from data you are permitted to
use, or connect an authorized source API/export before relying on catalog
prices.
