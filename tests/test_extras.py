import json

from job_hunter.extras import build_extras, compact_extras, description_keys


def test_compact_drops_empties_description_keys_and_long_strings_but_keeps_the_rest():
    payload = {
        "Category": "PD Operations and Quality", "JobFamily": None, "Empty": "", "Nested": {"a": None, "b": 1},
        "Flags": [False, None, 0], "ExternalDescriptionStr": "<p>big</p>", "Huge": "x" * 5000,
    }
    out = compact_extras(payload, skip_keys=["ExternalDescriptionStr"])
    assert out["Category"] == "PD Operations and Quality"
    assert out["Nested"] == {"b": 1}
    assert out["Flags"] == [False, 0]  # real falsy values survive; only empties are dropped
    assert "JobFamily" not in out and "Empty" not in out and "ExternalDescriptionStr" not in out
    assert "Huge" not in out and out["_omitted_long"] == ["Huge"]
    assert compact_extras(None) == {} and compact_extras([1]) == {}


def test_build_extras_combines_parts_and_is_none_when_empty():
    assert build_extras({}, None) is None
    assert build_extras({"a": 1}, {"b": 2}) == {"listing": {"a": 1}, "detail": {"b": 2}}


def test_build_extras_shrinks_an_oversized_result():
    big = {f"k{i}": "y" * 1500 for i in range(30)}  # each under MAX_STRING, together over the cap
    out = build_extras(big, None)
    assert out is None or len(json.dumps(out)) < 20_000


def test_description_keys_take_the_first_path_segment_of_each_configured_field():
    cfg = {"detail_description_path": ["a.b", "c"], "listing_description_path": "desc.x"}
    assert description_keys(cfg) == ["a", "c", "desc", "description"]
