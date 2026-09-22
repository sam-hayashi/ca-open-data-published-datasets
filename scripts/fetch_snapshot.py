#!/usr/bin/env python
"""CLI: fetch a full snapshot of a CKAN catalog and export a classified CSV.

Useful for automation (e.g. a scheduled job) that keeps a snapshot on disk
for the Streamlit app, and/or for producing a one-off CSV export without
needing to launch the UI -- e.g. for archiving proof of the pre-migration
dataset inventory.

Usage:
    python scripts/fetch_snapshot.py
    python scripts/fetch_snapshot.py --ckan-url https://data.ca.gov --out audit.csv
    python scripts/fetch_snapshot.py --only-direct --out direct_published.csv

Exit codes:
    0 on success, 1 on any CKAN API error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this script directly (``python scripts/fetch_snapshot.py``)
# without having installed the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ca_open_data_audit.ckan_client import CKANAPIError, CKANClient
from ca_open_data_audit.config import get_settings
from ca_open_data_audit.pipeline import build_dataframe, fetch_all_packages, save_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ckan-url", default=None, help="Base CKAN URL (default: env CKAN_URL or data.ca.gov)")
    parser.add_argument("--api-key", default=None, help="CKAN API key (default: env CKAN_API_KEY)")
    parser.add_argument(
        "--out", default="ckan_dataset_publication_audit.csv", help="Output CSV path (default: %(default)s)"
    )
    parser.add_argument(
        "--only-direct", action="store_true", help="Only include directly-published (non-harvested) datasets"
    )
    parser.add_argument(
        "--only-harvested", action="store_true", help="Only include harvested datasets"
    )
    parser.add_argument(
        "--no-cache-write", action="store_true", help="Skip writing the on-disk cache snapshot"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings(ckan_url=args.ckan_url, api_key=args.api_key)
    client = CKANClient(settings)

    print(f"Fetching datasets from {settings.ckan_url} ...")

    def progress(fetched: int, total: int) -> None:
        print(f"  {fetched:,} / {total:,}", end="\r")

    try:
        packages = fetch_all_packages(client, progress_callback=progress)
    except CKANAPIError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\nFetched {len(packages):,} datasets.")

    if not args.no_cache_write:
        cache_path = save_snapshot(packages, settings)
        print(f"Cached raw snapshot to {cache_path}")

    df = build_dataframe(packages)

    if args.only_direct and args.only_harvested:
        print("ERROR: --only-direct and --only-harvested are mutually exclusive", file=sys.stderr)
        return 1
    if args.only_direct:
        df = df[df["publication_method"] == "Directly Published"]
    elif args.only_harvested:
        df = df[df["publication_method"] == "Harvested"]

    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df):,} rows to {out_path}")

    direct_count = (df["publication_method"] == "Directly Published").sum() if "publication_method" in df else 0
    harvested_count = (df["publication_method"] == "Harvested").sum() if "publication_method" in df else 0
    print(f"Directly published: {direct_count:,} | Harvested: {harvested_count:,}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
