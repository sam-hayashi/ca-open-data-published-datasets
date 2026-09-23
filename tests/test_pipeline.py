"""Unit tests for ca_open_data_audit.pipeline dataframe building."""

import pandas as pd

from ca_open_data_audit.pipeline import (
    build_dataframe,
    extras_key_frequency,
)


def sample_packages():
    return [
        {
            "id": "1",
            "name": "direct-one",
            "title": "Direct One",
            "organization": {"name": "dept-a", "title": "Department A"},
            "extras": [],
            "resources": [{}, {}],
            "tags": [{"name": "foo"}],
            "private": False,
            "state": "active",
            "type": "dataset",
            "metadata_created": "2020-01-01T00:00:00",
            "metadata_modified": "2021-01-01T00:00:00",
        },
        {
            "id": "2",
            "name": "harvested-one",
            "title": "Harvested One",
            "organization": {"name": "dept-b", "title": "Department B"},
            "extras": [
                {"key": "harvest_object_id", "value": "obj-1"},
                {"key": "harvest_source_title", "value": "Upstream Portal"},
            ],
            "resources": [{}],
            "tags": [],
            "private": False,
            "state": "active",
            "type": "dataset",
            "metadata_created": "2020-06-01T00:00:00",
            "metadata_modified": "2021-06-01T00:00:00",
        },
    ]


def test_build_dataframe_basic_shape():
    df = build_dataframe(sample_packages())
    assert len(df) == 2
    assert set(df["publication_method"]) == {"Directly Published", "Harvested"}


def test_build_dataframe_harvest_source_populated():
    df = build_dataframe(sample_packages())
    harvested_row = df[df["name"] == "harvested-one"].iloc[0]
    assert harvested_row["harvest_source_title"] == "Upstream Portal"


def test_build_dataframe_empty_input_returns_empty_df():
    df = build_dataframe([])
    assert df.empty


def test_extras_key_frequency_counts_across_packages():
    freq = extras_key_frequency(sample_packages())
    assert freq["harvest_object_id"] == 1
    assert freq["harvest_source_title"] == 1


def test_direct_publish_api_endpoint_uses_ckan_base_url():
    df = build_dataframe(sample_packages(), ckan_base_url="https://data.ca.gov")
    row = df[df["name"] == "direct-one"].iloc[0]
    assert row["api_endpoint"] == "https://data.ca.gov/api/3/action/package_show?id=direct-one"
    assert row["api_endpoint_source"] == "data.ca.gov (direct)"


def test_harvested_api_endpoint_uses_harvest_url_extra_when_present():
    packages = sample_packages()
    packages[1]["extras"].append({"key": "harvest_url", "value": "https://upstream.example.gov/dataset/foo"})
    df = build_dataframe(packages, ckan_base_url="https://data.ca.gov")
    row = df[df["name"] == "harvested-one"].iloc[0]
    assert row["api_endpoint"] == "https://upstream.example.gov/dataset/foo"
    assert row["api_endpoint_source"] == "harvest_url extra"


def test_harvested_api_endpoint_uses_harvest_source_reference_url():
    packages = sample_packages()
    packages[1]["extras"].append(
        {"key": "harvest_source_reference", "value": "https://upstream.example.gov/api/3/action/package_show?id=abc"}
    )
    df = build_dataframe(packages, ckan_base_url="https://data.ca.gov")
    row = df[df["name"] == "harvested-one"].iloc[0]
    assert row["api_endpoint"] == "https://upstream.example.gov/api/3/action/package_show?id=abc"
    assert row["api_endpoint_source"] == "harvest_source_reference"


def test_harvested_api_endpoint_built_from_ckan_harvest_source_and_guid():
    packages = sample_packages()
    packages[1]["extras"].append({"key": "harvest_source_id", "value": "src-1"})
    packages[1]["extras"].append({"key": "guid", "value": "abc-123"})
    harvest_sources = [
        {"id": "src-1", "name": "src-1", "title": "Upstream Portal", "url": "https://upstream.example.gov", "source_type": "ckan"}
    ]
    df = build_dataframe(packages, ckan_base_url="https://data.ca.gov", harvest_sources=harvest_sources)
    row = df[df["name"] == "harvested-one"].iloc[0]
    assert row["api_endpoint"] == "https://upstream.example.gov/api/3/action/package_show?id=abc-123"
    assert row["api_endpoint_source"] == "harvest source (CKAN) + record id"
    assert row["harvest_source_url"] == "https://upstream.example.gov"


def test_harvested_api_endpoint_falls_back_to_base_url_for_non_ckan_source():
    packages = sample_packages()
    packages[1]["extras"].append({"key": "harvest_source_id", "value": "src-2"})
    harvest_sources = [
        {"id": "src-2", "name": "src-2", "title": "Upstream DCAT", "url": "https://upstream-dcat.example.gov", "source_type": "dcat"}
    ]
    df = build_dataframe(packages, ckan_base_url="https://data.ca.gov", harvest_sources=harvest_sources)
    row = df[df["name"] == "harvested-one"].iloc[0]
    assert row["api_endpoint"] == "https://upstream-dcat.example.gov"
    assert row["api_endpoint_source"] == "harvest source base URL"


def test_harvested_api_endpoint_unresolvable_returns_none():
    df = build_dataframe(sample_packages(), ckan_base_url="https://data.ca.gov")
    row = df[df["name"] == "harvested-one"].iloc[0]
    assert pd.isna(row["api_endpoint"])
    assert row["api_endpoint_source"] == "unavailable"
