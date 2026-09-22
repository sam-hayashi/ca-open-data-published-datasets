"""Logic for classifying a CKAN package as "harvested" vs. "directly published".

Background
----------
``data.ca.gov`` (like most CKAN portals) ingests datasets two ways:

1. **Direct publishing** -- an editor creates/edits the dataset by hand (or
   via the CKAN API on behalf of a human) directly within the CKAN instance.
2. **Harvesting** -- ``ckanext-harvest`` periodically pulls metadata from an
   external source (another CKAN, a Socrata/ArcGIS/DCAT/CSW endpoint, etc.)
   and creates/updates a package to mirror it. Harvested packages are tied to
   a *harvest source* and a *harvest object* record.

When ``ckanext-harvest`` creates or updates a package it stamps it with a set
of well-known ``extras`` (visible via ``package_show``/``package_search``).
The presence of **any** of these is a reliable, version-tolerant signal that
a dataset originated from a harvest job rather than being published by hand:

* ``harvest_object_id``       -- id of the ``harvest_object`` DB row
* ``harvest_source_id``       -- id of the configured harvest source
* ``harvest_source_title``    -- display name of the harvest source
* ``harvest_source_reference``-- source-side identifier/URL
* ``guid``                    -- the source's own identifier for the record
* ``source_hash``             -- hash CKAN uses to detect upstream changes
* ``metadata_source``         -- occasionally set by DCAT/other harvesters

Some CKAN forks/extensions surface a subset of these as first-class fields on
the package dict itself (not nested in ``extras``); we check both locations.

This module intentionally avoids hard-coding organization/harvest-source
names so it keeps working as new harvest sources are added/removed --
instead it looks for the structural fingerprint ``ckanext-harvest`` leaves
behind. Organization- and harvest-source-based signals are still surfaced in
the resulting dataframe for extra context and for use as filters in the
Streamlit UI, but they aren't used to decide the classification.

References:
    https://github.com/ckan/ckanext-harvest
    https://docs.ckan.org/projects/ckanext-harvest/en/latest/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Extra/field keys that ckanext-harvest (and common harvesters built on it)
# attach to a package to link it back to its harvest source/object.
HARVEST_INDICATOR_KEYS: frozenset[str] = frozenset(
    {
        "harvest_object_id",
        "harvest_source_id",
        "harvest_source_title",
        "harvest_source_reference",
        "harvest_url",
        "harvest_ng_source_id",
        "guid",
        "source_hash",
        "metadata_source",
    }
)


@dataclass
class HarvestDetection:
    """Result of inspecting a single package for harvest indicators."""

    is_harvested: bool
    matched_keys: list[str] = field(default_factory=list)
    harvest_source_title: str | None = None
    harvest_source_id: str | None = None
    guid: str | None = None

    @property
    def publication_method(self) -> str:
        return "Harvested" if self.is_harvested else "Directly Published"


def _extras_as_dict(package: dict[str, Any]) -> dict[str, Any]:
    """Normalize CKAN's ``extras`` (a list of ``{"key", "value"}`` dicts) to a dict."""

    extras = package.get("extras") or []
    out: dict[str, Any] = {}
    for item in extras:
        key = item.get("key")
        if key is not None:
            out[key] = item.get("value")
    return out


def detect_harvest(package: dict[str, Any]) -> HarvestDetection:
    """Inspect a single CKAN package dict and classify its publication method.

    A package is considered **harvested** if any known ckanext-harvest
    indicator key is present -- either as a top-level field on the package
    (some CKAN versions/extensions expose it there) or nested inside
    ``extras``. Everything else is treated as **directly published**.
    """

    extras = _extras_as_dict(package)
    matched = [k for k in HARVEST_INDICATOR_KEYS if package.get(k) or extras.get(k)]

    is_harvested = len(matched) > 0

    return HarvestDetection(
        is_harvested=is_harvested,
        matched_keys=matched,
        harvest_source_title=package.get("harvest_source_title") or extras.get("harvest_source_title"),
        harvest_source_id=package.get("harvest_source_id") or extras.get("harvest_source_id"),
        guid=package.get("guid") or extras.get("guid"),
    )
