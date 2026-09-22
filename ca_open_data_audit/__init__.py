"""Utilities for auditing datasets published on data.ca.gov (CKAN).

This package provides the building blocks used by the Streamlit app in
``app.py`` and the CLI snapshot tool in ``scripts/fetch_snapshot.py`` to:

1. Pull the full dataset catalog from a CKAN instance via the Action API.
2. Classify each dataset as either "directly published" on the platform
   or "harvested" from an upstream source via ``ckanext-harvest`` (or a
   similar harvesting mechanism).
3. Present/export the results so they can be used to verify that all
   directly-published datasets have been migrated to a new CKAN backend.
"""

from .config import Settings, get_settings
from .ckan_client import CKANClient, CKANAPIError, build_client
from .classifier import HarvestDetection, detect_harvest, HARVEST_INDICATOR_KEYS
from .pipeline import (
    fetch_all_packages,
    build_dataframe,
    extras_key_frequency,
    load_audit_data,
)

__all__ = [
    "Settings",
    "get_settings",
    "CKANClient",
    "CKANAPIError",
    "build_client",
    "HarvestDetection",
    "detect_harvest",
    "HARVEST_INDICATOR_KEYS",
    "fetch_all_packages",
    "build_dataframe",
    "extras_key_frequency",
    "load_audit_data",
]
