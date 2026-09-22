"""Unit tests for ca_open_data_audit.classifier.detect_harvest."""

from ca_open_data_audit.classifier import detect_harvest, HARVEST_INDICATOR_KEYS


def make_package(extras=None, **top_level):
    pkg = {
        "id": "abc-123",
        "name": "sample-dataset",
        "title": "Sample Dataset",
        "extras": extras or [],
    }
    pkg.update(top_level)
    return pkg


def test_no_indicators_is_directly_published():
    pkg = make_package()
    result = detect_harvest(pkg)
    assert result.is_harvested is False
    assert result.publication_method == "Directly Published"
    assert result.matched_keys == []


def test_harvest_object_id_in_extras_marks_harvested():
    pkg = make_package(extras=[{"key": "harvest_object_id", "value": "obj-1"}])
    result = detect_harvest(pkg)
    assert result.is_harvested is True
    assert result.publication_method == "Harvested"
    assert "harvest_object_id" in result.matched_keys


def test_harvest_source_title_top_level_field():
    pkg = make_package(harvest_source_title="Some Upstream Portal")
    result = detect_harvest(pkg)
    assert result.is_harvested is True
    assert result.harvest_source_title == "Some Upstream Portal"


def test_guid_in_extras_marks_harvested():
    pkg = make_package(extras=[{"key": "guid", "value": "upstream-guid-123"}])
    result = detect_harvest(pkg)
    assert result.is_harvested is True
    assert result.guid == "upstream-guid-123"


def test_unrelated_extras_do_not_trigger_harvest():
    pkg = make_package(
        extras=[
            {"key": "some_custom_field", "value": "foo"},
            {"key": "another_field", "value": "bar"},
        ]
    )
    result = detect_harvest(pkg)
    assert result.is_harvested is False
    assert result.matched_keys == []


def test_multiple_indicators_are_all_captured():
    pkg = make_package(
        extras=[
            {"key": "harvest_object_id", "value": "obj-1"},
            {"key": "harvest_source_id", "value": "src-1"},
            {"key": "guid", "value": "g-1"},
        ]
    )
    result = detect_harvest(pkg)
    assert result.is_harvested is True
    assert set(result.matched_keys) == {"harvest_object_id", "harvest_source_id", "guid"}


def test_empty_string_values_do_not_count_as_present():
    # ckanext-harvest never sets these to empty string in practice, but guard
    # against false positives if a package has a blank extra with one of
    # these keys.
    pkg = make_package(extras=[{"key": "guid", "value": ""}])
    result = detect_harvest(pkg)
    assert result.is_harvested is False


def test_all_indicator_keys_individually_trigger_harvested():
    for key in HARVEST_INDICATOR_KEYS:
        pkg = make_package(extras=[{"key": key, "value": "some-value"}])
        result = detect_harvest(pkg)
        assert result.is_harvested is True, f"Expected key {key!r} to trigger harvested classification"
