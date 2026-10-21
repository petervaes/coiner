# Coiner

Coiner is a Python command-line prototype for identifying coins from photos and
looking up source-attributed numismatic catalog prices. It uses an OpenAI vision
model for image identification and a local SQLite FTS5 index for catalog
retrieval, and includes a Streamlit interface for photo inspection and reports.

## Current capabilities

- Identify a coin from one photo with the OpenAI API.
- Inspect one or two uploaded coin photos in the Streamlit frontend.
- Search indexed catalog entries by text.
- Show the three closest source-attributed catalog entries and download a JSON
  valuation report.
- Show Numista and LeFranc price indications separately, with explicit
  cross-language grade matching.
- Require exact country and denomination matches, and an exact year match when
  the year was identified, before showing prices for an analyzed coin.
- Keep each catalog price linked to its source, grade/condition, currency, and
  date.
- Import JSON arrays and JSON Lines (`.jsonl`) catalog files.
- Parse saved Numista or LeFranc HTML price tables into catalog JSON without
  making network requests.

The repository includes a Numista 1 franc Morlon data snapshot for 1931–1941
in [`catalog/catalog.json`](catalog/catalog.json), with grade prices, mintages,
frequency figures, and LeFranc references. The 1935 Numista prices are listed
as VF €12, XF €15, and AU €19. LeFranc values for the same series are stored
separately in
[`catalog/lefranc_1_franc_morlon.json`](catalog/lefranc_1_franc_morlon.json),
preserving LeFranc's grades and EUR/USD values. Ingesting `catalog/` indexes
both sources. See the [catalog data instructions](catalog/sources/README.md)
for the format and source notes.

Catalog values are reference data, not a guaranteed current selling price or
appraisal. Coin condition is only a visual estimate and is not professional
grading. Live price fetching from Numista or LeFranc is not implemented; catalog
values must be provided as data that you are permitted to use.

## Requirements

- Python 3.11 or later
- An OpenAI API key for photo identification

## Install

From the repository root in PowerShell:

```powershell
python -m pip install -e .
Copy-Item .env.example .env
```

Edit `.env` and replace the `OPENAI_API_KEY` placeholder with your key. You may
also change `OPENAI_MODEL` there. Keep `.env` private; it is excluded by
`.gitignore`.

## Use

Index the included catalog:

```powershell
coiner ingest
```

By default, the index is written to `data/coiner.sqlite3` and source files are
read from `catalog/`. These paths can be overridden:

```powershell
coiner ingest --source-dir catalog --database data/coiner.sqlite3 --rebuild
```

Analyze a coin photo:

```powershell
coiner analyze .\coin.jpg
```

The command prints JSON containing the model's identification and matching
catalog prices, including source and condition. If there is no exact catalog
match, it reports that no price was inferred.

Search the indexed catalog directly:

```powershell
coiner search "France 1 franc 1935"
```

Start the Streamlit frontend:

```powershell
streamlit run src\coiner\streamlit_app.py
```

Upload one photo or both sides in the sidebar and select **Inspecteer munt**.
This sends the uploaded images to OpenAI Vision. The catalog values in this
prototype are recorded snapshots, not live quotes. A price indication is
calculated separately for each catalog source and currency when a recognized
equivalent grade is available. French and English grade abbreviations are
normalized for matching; the original source labels remain visible. These
cross-language equivalences are approximate and do not change the source data
or imply professional grading.

### Import a saved catalog HTML page

When an identified coin is missing locally, save a catalog page as UTF-8 HTML
using a method permitted by that source, then parse its grade/price table:

```powershell
python -m coiner parse-html .\coin-page.html `
  --source lefranc `
  --source-url "https://www.lefranc.net/monnaie,1-franc-morlon,219.html" `
  --country France `
  --denomination "1 franc" `
  --capture-date 2026-10-21 `
  --output .\catalog\imports\france-1-franc-morlon.html.json

python -m coiner ingest --source-dir catalog --database data/coiner.sqlite3 --rebuild
```

The generic parser detects common English/French grade headers, years, mintages,
and explicit currencies in HTML tables. It requires the coin identity and source
URL as inputs to avoid inventing them. The capture date is stored as the
snapshot date; the parser does not claim it is the source's quotation date.
This command only parses a local file: it does not search the web, download
pages, imitate a browser, or bypass HTTP errors or access controls. If a source
returns 4xx, use its official API, an authorized export, or ask its operator
for permission.

The module entry point is also available:

```powershell
python -m coiner --help
```

## Catalog data

Each JSON Lines record represents one price and requires an ID, coin
identification fields, source URL, price, currency, condition, and ISO-formatted
date. A JSON file can instead group grade prices in a `prices` object; the
index expands those into separate grade-specific entries. Supported sources
are `numista` and `lefranc`. Preserve source links and the grade to which each
price applies. Do not enter model-generated estimates as catalog prices.

Read [catalog/sources/README.md](catalog/sources/README.md) for a record example
and details of the supplied Numista and LeFranc snapshots.

## Tests

Run the test suite from the repository root:

```powershell
python -m pytest -q
```

## Privacy and security

The image supplied to `coiner analyze` is sent to the OpenAI API for
identification. Do not commit API keys, `.env`, or private coin images.
