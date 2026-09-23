"""End-to-end pipeline: fetch packages from CKAN, classify, and shape as a DataFrame.

This module is the glue between :mod:`ca_open_data_audit.ckan_client` and the
Streamlit UI / CLI snapshot script. It also implements a simple on-disk JSON
cache so repeated Streamlit reruns (or CLI invocations) don't need to hit
data.ca.gov every time, and so a snapshot can be captured for later
comparison once datasets are migrated to the new backend.

It also resolves, per dataset, an ``api_endpoint`` -- the CKAN Action API
endpoint on data.ca.gov for directly-published datasets, or a best-effort
guess at the *upstream source portal's* API endpoint for harvested datasets
(data.ca.gov is moving to a federated model where harvested datasets should
link back to their source portal's own API). See
:func:`_build_harvest_api_endpoint` for the resolution order used.
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
from .classifier import _extras_as_dict, detect_harvest
from .config import DEFAULT_CKAN_URL, Settings

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


def fetch_harvest_sources(client: CKANClient) -> list[dict[str, Any]]:
    """Fetch configured harvest sources (empty list if ckanext-harvest is unavailable).

    Each record typically includes ``id``, ``name``, ``title``, ``url`` (the
    upstream portal's base URL) and ``source_type``/``type`` (e.g. ``ckan``,
    ``dcat``, ``waf``, ``csw``). Used by :func:`build_dataframe` to resolve
    the *source portal's* API endpoint for harvested datasets.
    """

    return client.harvest_source_list()


def _first_extra(extras: Iterable[dict[str, Any]], key: str) -> Any:
    for item in extras or []:
        if item.get("key") == key:
            return item.get("value")
    return None


def _harvest_source_lookup(harvest_sources: Iterable[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Index harvest source records by both ``id`` and ``name`` for easy lookup."""

    lookup: dict[str, dict[str, Any]] = {}
    for src in harvest_sources or []:
        for key in (src.get("id"), src.get("name")):
            if key:
                lookup[key] = src
    return lookup


def _looks_like_url(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(("http://", "https://"))


def _harvest_source_type(source: dict[str, Any]) -> str:
    return str(source.get("source_type") or source.get("type") or "").strip().lower()


def _build_harvest_api_endpoint(
    extras: dict[str, Any],
    source: dict[str, Any] | None,
    guid: str | None,
) -> tuple[str | None, str]:
    """Best-effort resolution of the *upstream source portal's* API endpoint.

    Checked in order of specificity, since not every harvester/source
    exposes the same metadata:

    1. an explicit ``harvest_url`` extra -- some harvesters record the exact
       remote URL used to pull this specific record;
    2. ``harvest_source_reference`` when it is itself a URL -- WAF/CSW-style
       harvesters commonly store the remote document URL here;
    3. the configured harvest source's base ``url`` (from
       ``harvest_source_list``) combined with its ``source_type`` and the
       record's ``guid``/reference, to build a per-dataset API call when the
       upstream source is itself a CKAN instance;
    4. the harvest source's base URL alone, if the source type isn't one we
       know how to build a per-record endpoint for;
    5. the ``guid`` itself, if it happens to be a URL.

    Returns an ``(endpoint, provenance)`` tuple so the UI/export can show
    *how* the endpoint was derived alongside the result -- important for a
    migration-verification tool where "we guessed" vs. "explicitly recorded"
    matters.
    """

    harvest_url = extras.get("harvest_url")
    if _looks_like_url(harvest_url):
        return harvest_url, "harvest_url extra"

    reference = extras.get("harvest_source_reference")
    if _looks_like_url(reference):
        return reference, "harvest_source_reference"

    base_url = (source or {}).get("url")
    if base_url:
        base_url = str(base_url).rstrip("/")
        source_type = _harvest_source_type(source or {})
        identifier = guid or reference
        if source_type == "ckan":
            if identifier:
                return (
                    f"{base_url}/api/3/action/package_show?id={identifier}",
                    "harvest source (CKAN) + record id",
                )
            return f"{base_url}/api/3/action/package_search", "harvest source (CKAN) base API"
        return base_url, "harvest source base URL"

    if _looks_like_url(guid):
        return guid, "guid"

    return None, "unavailable"


def _row_from_package(
    pkg: dict[str, Any],
    ckan_base_url: str,
    harvest_source_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detection = detect_harvest(pkg)
    org = pkg.get("organization") or {}
    extras_list = pkg.get("extras") or []
    extras = _extras_as_dict(pkg)

    if detection.is_harvested:
        source = (harvest_source_lookup or {}).get(detection.harvest_source_id or "")
        api_endpoint, api_endpoint_source = _build_harvest_api_endpoint(extras, source, detection.guid)
        harvest_source_url = (source or {}).get("url")
    else:
        name = pkg.get("name")
        api_endpoint = (
            f"{ckan_base_url.rstrip('/')}/api/3/action/package_show?id={name}" if name else None
        )
        api_endpoint_source = "data.ca.gov (direct)"
        harvest_source_url = None

    return {
        "id": pkg.get("id"),
        "name": pkg.get("name"),
        "title": pkg.get("title"),
        "publication_method": detection.publication_method,
        "is_harvested": detection.is_harvested,
        "matched_harvest_keys": ", ".join(detection.matched_keys),
        "harvest_source_title": detection.harvest_source_title,
        "harvest_source_id": detection.harvest_source_id,
        "harvest_source_url": harvest_source_url,
        "guid": detection.guid,
        "api_endpoint": api_endpoint,
        "api_endpoint_source": api_endpoint_source,
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
        "metadata_source": pkg.get("metadata_source") or _first_extra(extras_list, "metadata_source"),
        "url": pkg.get("url"),
        "ckan_url": f"/dataset/{pkg.get('name')}" if pkg.get("name") else None,
        "notes": pkg.get("notes"),
        "num_extras": len(extras_list),
    }


def build_dataframe(
    packages: list[dict[str, Any]],
    ckan_base_url: str | None = None,
    harvest_sources: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Convert raw CKAN package dicts into a flat, analysis-friendly DataFrame.

    Args:
        packages: Raw package dicts from ``package_search``.
        ckan_base_url: Base URL used to build ``api_endpoint`` for
            directly-published datasets (defaults to
            :data:`ca_open_data_audit.config.DEFAULT_CKAN_URL`).
        harvest_sources: Optional harvest source records (from
            :func:`fetch_harvest_sources`), used to resolve the *upstream*
            API endpoint for harvested datasets.
    """

    base_url = ckan_base_url or DEFAULT_CKAN_URL
    lookup = _harvest_source_lookup(harvest_sources)
    rows = [_row_from_package(pkg, base_url, lookup) for pkg in packages]
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


def save_snapshot(
    packages: list[dict[str, Any]],
    settings: Settings,
    harvest_sources: list[dict[str, Any]] | None = None,
) -> Path:
    path = _cache_path(settings)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ckan_url": settings.ckan_url,
        "count": len(packages),
        "packages": packages,
        "harvest_sources": harvest_sources or [],
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
            df = build_dataframe(
                cached["packages"],
                ckan_base_url=cached.get("ckan_url") or settings.ckan_url,
                harvest_sources=cached.get("harvest_sources") or [],
            )
            meta = {
                "fetched_at": cached.get("fetched_at"),
                "ckan_url": cached.get("ckan_url"),
                "count": cached.get("count"),
                "source": "cache",
            }
            return df, meta

    packages = fetch_all_packages(client, progress_callback=progress_callback)
    harvest_sources = fetch_harvest_sources(client)
    save_snapshot(packages, settings, harvest_sources=harvest_sources)
    df = build_dataframe(packages, ckan_base_url=settings.ckan_url, harvest_sources=harvest_sources)
    meta = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ckan_url": settings.ckan_url,
        "count": len(packages),
        "source": "live",
    }
    return df, meta
