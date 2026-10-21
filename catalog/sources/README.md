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

## Parsing a saved HTML snapshot

The generic standard-library parser supports local HTML tables whose header
cells use recognized grade labels (for example `G`, `F`, `VF`, `B`, `TB`,
`TTB`, `SUP`, `SPL`, and `FDC`). It can also extract a year, mintage, and
explicit currency where present. Provide the country, denomination, source URL,
and capture date explicitly. It creates the same grouped `prices` records
accepted by the catalog index:

```powershell
python -m coiner parse-html .\coin-page.html `
  --source lefranc `
  --source-url "https://www.lefranc.net/monnaie,1-franc-morlon,219.html" `
  --country France `
  --denomination "1 franc" `
  --capture-date 2026-10-21 `
  --output .\catalog\imports\france-1-franc-morlon.html.json
```

The parser is intentionally offline. It does not fetch URLs or bypass source
access controls. The capture date is not treated as the source's quotation date
unless the source itself provides that date separately.

## Grade-label matching

The interface preserves the grade as published by each catalog, and also
normalizes recognized English/French labels for retrieval and comparison:

| Normalized grade | Recognized labels |
| --- | --- |
| G | G, Good |
| VG | VG, Very Good, TB, Très Beau |
| F | F, Fine, B, Beau |
| VF | VF, Very Fine, TTB, Très Très Beau |
| XF | XF, EF, Extremely Fine, SUP, Superbe |
| AU | AU, About Uncirculated, SPL, Splendide |
| UNC | UNC, Uncirculated, MS, Mint State, FDC, Fleur de Coin |

In particular, **B (Beau) is matched to F (Fine)** as requested. The French /
English equivalences are approximate lookup aliases, not an official universal
conversion between grading systems. Stored prices and grade labels are never
rewritten. Numista and LeFranc values are displayed separately and are not
averaged across sources or converted between currencies. For background on the
numeric grading scale, see [NGC's grading scale](https://www.ngccoin.com/coin-grading/grading-scale/).
