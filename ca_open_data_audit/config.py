"""Runtime configuration for the CKAN audit tooling.

Settings can be supplied via environment variables (optionally loaded from a
``.env`` file) or overridden at runtime -- e.g. from the Streamlit sidebar --
without ever committing secrets such as API keys to source control.

Environment variables recognized:

* ``CKAN_URL``           -- Base URL of the CKAN instance (default: the
                             production data.ca.gov catalog).
* ``CKAN_API_KEY``       -- Optional API token. Only required to see private
                             datasets the requesting user/org can access.
* ``CKAN_ROWS_PER_PAGE`` -- Page size used when paginating ``package_search``
                             (default: 1000, CKAN's typical max).
* ``CKAN_TIMEOUT``       -- Per-request timeout, in seconds (default: 30).
* ``CKAN_MAX_RETRIES``   -- Number of retries for transient HTTP failures.
* ``CACHE_DIR``          -- Directory used to store on-disk snapshots so the
                             Streamlit app can work offline / avoid refetching
                             on every rerun (default: ``.cache``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # pragma: no cover - optional dependency convenience
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEFAULT_CKAN_URL = "https://data.ca.gov"


@dataclass
class Settings:
    """Container for all configurable values used across the package."""

    ckan_url: str = field(default_factory=lambda: os.getenv("CKAN_URL", DEFAULT_CKAN_URL))
    api_key: str | None = field(default_factory=lambda: os.getenv("CKAN_API_KEY") or None)
    rows_per_page: int = field(default_factory=lambda: int(os.getenv("CKAN_ROWS_PER_PAGE", "1000")))
    timeout: int = field(default_factory=lambda: int(os.getenv("CKAN_TIMEOUT", "30")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("CKAN_MAX_RETRIES", "3")))
    include_private: bool = field(default_factory=lambda: os.getenv("CKAN_INCLUDE_PRIVATE", "true").lower() == "true")
    cache_dir: Path = field(default_factory=lambda: Path(os.getenv("CACHE_DIR", ".cache")))

    def __post_init__(self) -> None:
        self.ckan_url = self.ckan_url.rstrip("/")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def action_api_url(self) -> str:
        return f"{self.ckan_url}/api/3/action"


def get_settings(**overrides) -> Settings:
    """Return a :class:`Settings` instance, applying any keyword overrides.

    Useful from the Streamlit sidebar where the user may want to point at a
    staging CKAN instance or supply an API key for a single session without
    mutating environment variables.
    """

    base = Settings()
    if not overrides:
        return base
    data = base.__dict__.copy()
    data.update({k: v for k, v in overrides.items() if v is not None})
    # cache_dir may come back in as a plain str from a UI widget.
    if isinstance(data.get("cache_dir"), str):
        data["cache_dir"] = Path(data["cache_dir"])
    return Settings(**data)
