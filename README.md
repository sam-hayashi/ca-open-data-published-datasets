# ca-open-data-published-datasets

Audit tooling to identify which datasets on a CKAN Open Data portal (e.g.
[data.ca.gov](https://data.ca.gov)) were **directly published** by an editor
versus **harvested** from an upstream source via
[`ckanext-harvest`](https://github.com/ckan/ckanext-harvest). This is used to
verify that every directly-published dataset -- which has no upstream system
of record to re-harvest from -- has been correctly migrated to a new CKAN
backend.

## How classification works

CKAN's harvesting extension (`ckanext-harvest`) stamps every package it
creates/updates with metadata that ties it back to a harvest source and a
harvest object record. These show up either as top-level fields or nested
inside a package's `extras`, depending on the CKAN version/extension:

- `harvest_object_id`
- `harvest_source_id`
- `harvest_source_title`
- `harvest_source_reference`
- `harvest_url`
- `harvest_ng_source_id`
- `guid`
- `source_hash`
- `metadata_source`

A dataset is classified as **Harvested** if *any* of these are present, and
as **Directly Published** otherwise. See
[`ca_open_data_audit/classifier.py`](ca_open_data_audit/classifier.py:1) for
the implementation and
[`ca_open_data_audit.classifier.HARVEST_INDICATOR_KEYS`](ca_open_data_audit/classifier.py:56).

This approach doesn't hard-code organization or harvest-source names, so it
keeps working as harvest sources are added or removed. The app's
**Diagnostics** panel also surfaces a frequency count of every `extras` key
seen across the catalog, to help confirm coverage or spot new indicator keys
worth adding.

## Project layout

```
ca_open_data_audit/
  config.py        # Settings (CKAN URL, API key, pagination, cache dir)
  ckan_client.py    # Thin CKAN Action API client (package_search pagination)
  classifier.py     # Harvested vs. Directly Published detection logic
  pipeline.py       # Fetch -> DataFrame + on-disk snapshot caching
app.py              # Streamlit UI: filters, metrics, export
scripts/
  fetch_snapshot.py # CLI: fetch + export CSV without the UI
tests/              # pytest unit tests for classifier + pipeline
```

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env   # then edit values as needed
```

## Run the Streamlit app

```powershell
streamlit run app.py
```

In the sidebar:

1. Confirm/adjust the **CKAN base URL** (defaults to `https://data.ca.gov`).
2. Optionally supply an **API key** to include private datasets.
3. Click **🔄 Fetch live** to pull the full catalog (paginated automatically),
   or **📂 Load cache** to reuse the last fetched snapshot without hitting
   the network.

The main panel then lets you:

- Filter by publication method, organization, harvest source, or free-text
  search.
- View summary metrics (total / directly published / harvested / currently
  filtered counts) and a per-organization breakdown.
- Browse the full results table with clickable source URLs.
- **Export** the filtered (or full) results as CSV or Excel.

## Run the CLI snapshot tool

For automation or one-off exports without launching the UI:

```powershell
python scripts/fetch_snapshot.py --out ckan_dataset_publication_audit.csv
python scripts/fetch_snapshot.py --only-direct --out direct_published.csv
python scripts/fetch_snapshot.py --ckan-url https://data.ca.gov --api-key $env:CKAN_API_KEY
```

Run `python scripts/fetch_snapshot.py --help` for all options.

## Run tests

```powershell
pytest
```

## Configuration reference

All settings can be supplied via environment variables (optionally from a
`.env` file, see [`.env.example`](.env.example:1)) and can also be overridden
per-session from the Streamlit sidebar:

| Variable              | Default                | Purpose                                             |
|-----------------------|-------------------------|------------------------------------------------------|
| `CKAN_URL`            | `https://data.ca.gov`   | Base URL of the CKAN instance                        |
| `CKAN_API_KEY`        | *(none)*                | API token; required to see private datasets          |
| `CKAN_ROWS_PER_PAGE`  | `1000`                  | Page size for `package_search` pagination            |
| `CKAN_TIMEOUT`        | `30`                    | Per-request timeout (seconds)                        |
| `CKAN_MAX_RETRIES`    | `3`                     | Retries for transient HTTP errors (429/5xx)          |
| `CKAN_INCLUDE_PRIVATE`| `true`                  | Whether to request private datasets                  |
| `CACHE_DIR`           | `.cache`                | Directory for the on-disk snapshot cache              |

## References

- [CKAN Action API docs](https://docs.ckan.org/en/latest/api/)
- [`ckanext-harvest` documentation](https://docs.ckan.org/projects/ckanext-harvest/en/latest/)
- [data.ca.gov](https://data.ca.gov)
