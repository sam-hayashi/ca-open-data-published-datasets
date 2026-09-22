"""Streamlit app: audit data.ca.gov datasets by publication method.

Identifies which CKAN datasets were published directly on the platform vs.
harvested from an upstream source (via ``ckanext-harvest``), so migration to
a new CKAN backend can be verified as complete -- specifically that every
*directly published* dataset (which has no upstream system of record to
re-harvest from) has been re-created/migrated.

Run with:
    streamlit run app.py

Configuration (env vars, optionally via a ``.env`` file):
    CKAN_URL, CKAN_API_KEY, CKAN_ROWS_PER_PAGE, CKAN_TIMEOUT,
    CKAN_MAX_RETRIES, CKAN_INCLUDE_PRIVATE, CACHE_DIR
See ca_open_data_audit/config.py for details.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from ca_open_data_audit.ckan_client import CKANAPIError, CKANClient
from ca_open_data_audit.config import get_settings
from ca_open_data_audit.pipeline import (
    build_dataframe,
    extras_key_frequency,
    fetch_all_packages,
    load_snapshot,
    save_snapshot,
)

st.set_page_config(
    page_title="data.ca.gov Publication Method Audit",
    page_icon="🗂️",
    layout="wide",
)

DISPLAY_COLUMNS = [
    "title",
    "name",
    "organization",
    "publication_method",
    "harvest_source_title",
    "matched_harvest_keys",
    "num_resources",
    "private",
    "state",
    "metadata_created",
    "metadata_modified",
    "url",
    "ckan_url",
]


# --------------------------------------------------------------------------
# Sidebar: connection settings + fetch controls
# --------------------------------------------------------------------------

def render_sidebar():
    st.sidebar.header("CKAN Connection")
    default_settings = get_settings()

    ckan_url = st.sidebar.text_input(
        "CKAN base URL", value=default_settings.ckan_url,
        help="Base URL of the CKAN instance, e.g. https://data.ca.gov",
    )
    api_key = st.sidebar.text_input(
        "API key (optional)",
        value=default_settings.api_key or "",
        type="password",
        help="Only needed to include private datasets visible to your account.",
    )
    include_private = st.sidebar.checkbox(
        "Include private datasets", value=default_settings.include_private
    )
    rows_per_page = st.sidebar.number_input(
        "Page size", min_value=100, max_value=1000, value=default_settings.rows_per_page, step=100
    )

    settings = get_settings(
        ckan_url=ckan_url.strip() or default_settings.ckan_url,
        api_key=api_key.strip() or None,
        include_private=include_private,
        rows_per_page=int(rows_per_page),
    )

    st.sidebar.divider()
    st.sidebar.header("Data")

    col1, col2 = st.sidebar.columns(2)
    fetch_clicked = col1.button("🔄 Fetch live", use_container_width=True)
    use_cache_clicked = col2.button("📂 Load cache", use_container_width=True)

    return settings, fetch_clicked, use_cache_clicked


# --------------------------------------------------------------------------
# Data loading (with Streamlit session state so we don't refetch on every
# widget interaction -- only on explicit user action).
# --------------------------------------------------------------------------

def do_live_fetch(settings) -> None:
    client = CKANClient(settings)
    progress_bar = st.sidebar.progress(0, text="Connecting to CKAN...")

    def _progress(fetched: int, total: int) -> None:
        pct = min(fetched / total, 1.0) if total else 0.0
        progress_bar.progress(pct, text=f"Fetched {fetched:,} / {total:,} datasets")

    try:
        packages = fetch_all_packages(client, progress_callback=_progress)
    except CKANAPIError as exc:
        progress_bar.empty()
        st.sidebar.error(f"Fetch failed: {exc}")
        return

    save_snapshot(packages, settings)
    progress_bar.empty()
    st.session_state["packages"] = packages
    st.session_state["meta"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ckan_url": settings.ckan_url,
        "count": len(packages),
        "source": "live",
    }
    st.sidebar.success(f"Fetched {len(packages):,} datasets.")


def do_load_cache(settings) -> None:
    cached = load_snapshot(settings)
    if not cached:
        st.sidebar.warning("No cached snapshot found yet. Fetch live first.")
        return
    st.session_state["packages"] = cached["packages"]
    st.session_state["meta"] = {
        "fetched_at": cached.get("fetched_at"),
        "ckan_url": cached.get("ckan_url"),
        "count": cached.get("count"),
        "source": "cache",
    }
    st.sidebar.info(f"Loaded {cached.get('count', 0):,} datasets from cache.")


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="datasets")
    return buffer.getvalue()


def main():
    st.title("🗂️ data.ca.gov Publication Method Audit")
    st.caption(
        "Classifies every dataset on a CKAN instance as **Directly Published** "
        "or **Harvested**, to help verify migration completeness to a new backend."
    )

    settings, fetch_clicked, use_cache_clicked = render_sidebar()

    if fetch_clicked:
        do_live_fetch(settings)
    elif use_cache_clicked:
        do_load_cache(settings)

    if "packages" not in st.session_state:
        st.info(
            "Use the sidebar to **Fetch live** data from CKAN, or **Load cache** "
            "if you've fetched previously in this environment."
        )
        return

    packages = st.session_state["packages"]
    meta = st.session_state["meta"]
    df = build_dataframe(packages)

    st.caption(
        f"Data source: **{meta['source']}** · CKAN: `{meta['ckan_url']}` · "
        f"Fetched: {meta['fetched_at']} · Total datasets: **{meta['count']:,}**"
    )

    if df.empty:
        st.warning("No datasets returned.")
        return

    # ----------------------------------------------------------------
    # Filters
    # ----------------------------------------------------------------
    st.subheader("Filters")
    fcol1, fcol2, fcol3, fcol4 = st.columns([1.2, 1.5, 1.5, 1.5])

    with fcol1:
        method_options = ["Directly Published", "Harvested"]
        methods = st.multiselect("Publication method", method_options, default=method_options)

    with fcol2:
        orgs = sorted(df["organization"].dropna().unique().tolist())
        selected_orgs = st.multiselect("Organization", orgs)

    with fcol3:
        harvest_sources = sorted(df["harvest_source_title"].dropna().unique().tolist())
        selected_sources = st.multiselect("Harvest source", harvest_sources)

    with fcol4:
        search_text = st.text_input("Search title/name", "")

    filtered = df[df["publication_method"].isin(methods)]
    if selected_orgs:
        filtered = filtered[filtered["organization"].isin(selected_orgs)]
    if selected_sources:
        filtered = filtered[filtered["harvest_source_title"].isin(selected_sources)]
    if search_text:
        needle = search_text.lower()
        filtered = filtered[
            filtered["title"].fillna("").str.lower().str.contains(needle)
            | filtered["name"].fillna("").str.lower().str.contains(needle)
        ]

    # ----------------------------------------------------------------
    # Summary metrics
    # ----------------------------------------------------------------
    st.subheader("Summary")
    total = len(df)
    direct_count = int((df["publication_method"] == "Directly Published").sum())
    harvested_count = int((df["publication_method"] == "Harvested").sum())
    filtered_count = len(filtered)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total datasets", f"{total:,}")
    m2.metric("Directly published", f"{direct_count:,}", help="No ckanext-harvest indicators found")
    m3.metric("Harvested", f"{harvested_count:,}", help="Has ckanext-harvest indicators")
    m4.metric("Matching current filters", f"{filtered_count:,}")

    by_org = (
        df.groupby(["organization", "publication_method"]).size().unstack(fill_value=0)
        if not df.empty
        else pd.DataFrame()
    )
    with st.expander("Breakdown by organization"):
        st.dataframe(by_org, use_container_width=True)

    # ----------------------------------------------------------------
    # Results table
    # ----------------------------------------------------------------
    st.subheader(f"Datasets ({filtered_count:,} shown)")
    display_df = filtered[[c for c in DISPLAY_COLUMNS if c in filtered.columns]]
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "url": st.column_config.LinkColumn("Source URL"),
            "ckan_url": st.column_config.TextColumn("CKAN dataset path"),
        },
    )

    # ----------------------------------------------------------------
    # Export
    # ----------------------------------------------------------------
    st.subheader("Export")
    ecol1, ecol2, ecol3 = st.columns(3)
    ecol1.download_button(
        "⬇️ Download filtered CSV",
        data=to_csv_bytes(filtered),
        file_name="ckan_dataset_publication_audit.csv",
        mime="text/csv",
        use_container_width=True,
    )
    ecol2.download_button(
        "⬇️ Download all datasets CSV",
        data=to_csv_bytes(df),
        file_name="ckan_dataset_publication_audit_full.csv",
        mime="text/csv",
        use_container_width=True,
    )
    ecol3.download_button(
        "⬇️ Download filtered Excel",
        data=to_excel_bytes(filtered),
        file_name="ckan_dataset_publication_audit.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    # ----------------------------------------------------------------
    # Diagnostics: raw extras key frequency (helps validate classifier)
    # ----------------------------------------------------------------
    with st.expander("🔧 Diagnostics: extras key frequency (advanced)"):
        st.caption(
            "Counts how often each `extras` key appears across all fetched "
            "datasets. Useful for confirming which harvest-indicator keys "
            "this CKAN instance actually uses, or spotting new ones to add "
            "to the classifier."
        )
        freq = extras_key_frequency(packages)
        freq_df = pd.DataFrame(sorted(freq.items(), key=lambda kv: -kv[1]), columns=["extras_key", "count"])
        st.dataframe(freq_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
