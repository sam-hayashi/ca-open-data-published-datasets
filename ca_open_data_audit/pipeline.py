"""End-to-end pipeline: fetch packages from CKAN, classify, and shape as a DataFrame.

This module is the glue between :mod:`ca_open_data_audit.ckan_client` and the
Streamlit UI / CLI snapshot script. It also implements a simple on-disk JSON
cache so repeated Streamlit reruns (or CLI invocations) don't need to hit
data.ca.gov every time, and so a snapshot can be captured for later
comparison once datasets are migrated to the new backend.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from .ckan_client import CKANClient
from .classifier import detect_harvest
from .config import Settings

logger = logging.getLogger(__name__)

CACHE_FILENAME = "ckan_package_snapshot.json"


def fetch_all_packages(
    client: CKANClient,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Fetch every package (dataset) from the target CKAN instance.

    Returns the raw list of package dicts as returned by ``package_search``,
    unmodified, so downstream code can decide what to keep.
    """

    return list(client.iter_all_packages(progress_callback=progress_callback))


def _first_extra(extras: Iterable[dict[str, Any]], key: str) -> Any:
    for item in extras or []:
        if item.get("key") == key:
            return item.get("value")
    return None


def _row_from_package(pkg: dict[str, Any]) -> dict[str, Any]:
    detection = detect_harvest(pkg)
    org = pkg.get("organization") or {}
    extras = pkg.get("extras") or []

    return {
        "id": pkg.get("id"),
        "name": pkg.get("name"),
        "title": pkg.get("title"),
        "publication_method": detection.publication_method,
        "is_harvested": detection.is_harvested,
        "matched_harvest_keys": ", ".join(detection.matched_keys),
        "harvest_source_title": detection.harvest_source_title,
        "harvest_source_id": detection.harvest_source_id,
        "guid": detection.guid,
        "organization": org.get("title") or org.get("name"),
        "organization_name": org.get("name"),
        "maintainer": pkg.get("maintainer"),
        "author": pkg.get("author"),
        "license_title": pkg.get("license_title"),
        "num_resources": len(pkg.get("resources") or []),
        "num_tags": len(pkg.get("tags") or []),
        "private": pkg.get("private"),
        "state": pkg.get("state"),
        "type": pkg.get("type"),
        "metadata_created": pkg.get("metadata_created"),
        "metadata_modified": pkg.get("metadata_modified"),
        "metadata_source": pkg.get("metadata_source") or _first_extra(extras, "metadata_source"),
        "url": pkg.get("url"),
        "ckan_url": f"/dataset/{pkg.get('name')}" if pkg.get("name") else None,
        "notes": pkg.get("notes"),
        "num_extras": len(extras),
    }


def build_dataframe(packages: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert raw CKAN package dicts into a flat, analysis-friendly DataFrame."""

    rows = [_row_from_package(pkg) for pkg in packages]
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for col in ("metadata_created", "metadata_modified"):
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df = df.sort_values("title", na_position="last").reset_index(drop=True)
    return df


def extras_key_frequency(packages: list[dict[str, Any]]) -> Counter:
    """Count how often each ``extras`` key appears across all packages.

    Handy for auditing: confirms which harvest-indicator keys are actually
    present on this CKAN instance, and surfaces any custom/unexpected extras
    keys that might warrant adding to
    :data:`ca_open_data_audit.classifier.HARVEST_INDICATOR_KEYS`.
    """

    counter: Counter = Counter()
    for pkg in packages:
        for item in pkg.get("extras") or []:
            key = item.get("key")
            if key:
                counter[key] += 1
    return counter


def _cache_path(settings: Settings) -> Path:
    return settings.cache_dir / CACHE_FILENAME


def save_snapshot(packages: list[dict[str, Any]], settings: Settings) -> Path:
    path = _cache_path(settings)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ckan_url": settings.ckan_url,
        "count": len(packages),
        "packages": packages,
    }
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")
    return path


def load_snapshot(settings: Settings) -> dict[str, Any] | None:
    path = _cache_path(settings)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load cached snapshot at %s: %s", path, exc)
        return None


def load_audit_data(
    client: CKANClient,
    settings: Settings,
    use_cache: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load (from cache or live) and return ``(dataframe, metadata)``.

    ``metadata`` includes ``fetched_at``, ``ckan_url``, and ``count`` so the
    UI can show provenance/freshness of the currently displayed data.
    """

    if use_cache:
        cached = load_snapshot(settings)
        if cached:
            df = build_dataframe(cached["packages"])
            meta = {
                "fetched_at": cached.get("fetched_at"),
                "ckan_url": cached.get("ckan_url"),
                "count": cached.get("count"),
                "source": "cache",
            }
            return df, meta

    packages = fetch_all_packages(client, progress_callback=progress_callback)
    save_snapshot(packages, settings)
    df = build_dataframe(packages)
    meta = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ckan_url": settings.ckan_url,
        "count": len(packages),
        "source": "live",
    }
    return df, meta
