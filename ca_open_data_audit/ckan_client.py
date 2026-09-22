"""Thin wrapper around the CKAN Action API used by data.ca.gov.

Only the endpoints needed for the harvest-vs-direct-publish audit are
implemented: ``package_search`` (paginated), ``organization_list``,
``group_list`` and ``harvest_source_list``. All calls go through the public,
unauthenticated Action API by default; supply an API key in :class:`Settings`
to also see private datasets visible to that user/organization.

Reference docs:
    https://docs.ckan.org/en/latest/api/
    https://github.com/ckan/ckanext-harvest
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings

logger = logging.getLogger(__name__)


class CKANAPIError(RuntimeError):
    """Raised when the CKAN Action API returns success=false or a bad HTTP status."""

    def __init__(self, action: str, message: str, payload: Any = None):
        super().__init__(f"CKAN action '{action}' failed: {message}")
        self.action = action
        self.payload = payload


@dataclass
class CKANClient:
    """Minimal, dependency-light CKAN Action API client."""

    settings: Settings

    def __post_init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=self.settings.max_retries,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        if self.settings.api_key:
            self._session.headers["Authorization"] = self.settings.api_key
        self._session.headers["User-Agent"] = "ca-open-data-published-datasets-audit/1.0"

    def call_action(self, action: str, **params: Any) -> Any:
        """Invoke a CKAN Action API endpoint and return its ``result`` payload."""

        url = f"{self.settings.action_api_url}/{action}"
        try:
            response = self._session.get(url, params=params, timeout=self.settings.timeout)
        except requests.RequestException as exc:  # network-level failure
            raise CKANAPIError(action, str(exc)) from exc

        if response.status_code >= 400:
            raise CKANAPIError(
                action,
                f"HTTP {response.status_code}: {response.text[:500]}",
                payload=params,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise CKANAPIError(action, "Response was not valid JSON") from exc

        if not data.get("success", False):
            raise CKANAPIError(action, str(data.get("error")), payload=params)

        return data.get("result")

    def package_search(
        self,
        rows: int = 1000,
        start: int = 0,
        fq: str | None = None,
        sort: str = "metadata_created asc",
        include_private: bool = True,
    ) -> dict:
        """Call ``package_search``, returning the raw result dict (with ``count``/``results``)."""

        params: dict[str, Any] = {
            "rows": rows,
            "start": start,
            "sort": sort,
            "include_private": str(include_private).lower(),
        }
        if fq:
            params["fq"] = fq
        return self.call_action("package_search", **params)

    def iter_all_packages(
        self,
        page_size: int | None = None,
        fq: str | None = None,
        include_private: bool | None = None,
        progress_callback=None,
    ) -> Iterable[dict]:
        """Yield every package (dataset) in the catalog, handling pagination.

        Args:
            page_size: Override the configured rows-per-page.
            fq: Optional Solr filter query passed through to ``package_search``.
            include_private: Whether to include private datasets (requires an
                API key with appropriate permissions). Defaults to the
                configured setting.
            progress_callback: Optional ``callable(fetched: int, total: int)``
                invoked after each page, useful for driving a Streamlit
                progress bar.
        """

        rows = page_size or self.settings.rows_per_page
        include_private = (
            self.settings.include_private if include_private is None else include_private
        )
        start = 0
        total = None
        fetched = 0

        while True:
            result = self.package_search(
                rows=rows, start=start, fq=fq, include_private=include_private
            )
            total = result.get("count", 0) if total is None else total
            batch = result.get("results", [])
            if not batch:
                break
            for pkg in batch:
                yield pkg
            fetched += len(batch)
            if progress_callback:
                progress_callback(fetched, total)
            start += len(batch)
            if fetched >= total or len(batch) < rows:
                break

    def organization_list(self, all_fields: bool = True) -> list[dict]:
        return self.call_action("organization_list", all_fields=str(all_fields).lower())

    def group_list(self, all_fields: bool = True) -> list[dict]:
        return self.call_action("group_list", all_fields=str(all_fields).lower())

    def harvest_source_list(self) -> list[dict]:
        """List configured harvest sources, if ``ckanext-harvest`` is enabled.

        Returns an empty list (rather than raising) if the action is
        unavailable, since not every CKAN instance exposes it publicly.
        """

        try:
            return self.call_action("harvest_source_list")
        except CKANAPIError as exc:
            logger.info("harvest_source_list unavailable: %s", exc)
            return []

    def site_read(self) -> bool:
        """Simple connectivity/health check against the target CKAN instance."""

        try:
            return bool(self.call_action("site_read"))
        except CKANAPIError:
            return False


def build_client(settings: Settings | None = None) -> CKANClient:
    """Construct a :class:`CKANClient`, defaulting to environment-derived settings."""

    from .config import get_settings

    return CKANClient(settings or get_settings())
