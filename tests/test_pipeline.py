"""Unit tests for ca_open_data_audit.pipeline dataframe building."""

from ca_open_data_audit.pipeline import build_dataframe, extras_key_frequency


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
