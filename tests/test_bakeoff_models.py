import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import bakeoff_models as bk  # noqa: E402
import build_golden_jobs as golden_builder  # noqa: E402


def _model(key, size, options=None):
    caps = {"reasoning": {"allowed_options": options}} if options else {}
    return {"key": key, "type": "llm", "size_bytes": size, "capabilities": caps}


class _FakeClient:
    def __init__(self, models):
        self._models = models

    def get(self, url, timeout=0):
        class R:
            def json(_self):  # noqa: N805
                return {"models": self._models}

        return R()


def test_modes_follow_each_models_own_reasoning_options():
    assert bk.modes_for(_model("a", 1)) == ["default"]
    assert bk.modes_for(_model("a", 1, ["off", "on"])) == ["off", "default"]
    assert bk.modes_for(_model("a", 1, ["off", "low", "medium", "xhigh", "on"])) == ["off", "low", "default"]
    assert bk.modes_for(_model("a", 1, ["on"])) == ["default"]


def test_plan_runs_fast_stages_first_skips_missing_models_and_small_before_large():
    models = [
        _model("big", 30, ["off", "on"]), _model("small", 4, ["off", "on"]),
        _model("plain", 3),  # no thinking switch: one fast run, goes first
        _model("mid", 20, ["off", "low", "on"]),
    ]
    plan, skipped = bk.build_plan(_FakeClient(models), "http://x", ["big", "small", "plain", "mid", "absent"], None)
    assert skipped == ["absent"]
    assert plan == [
        ("plain", "default"), ("small", "off"), ("mid", "off"), ("big", "off"),
        ("mid", "low"), ("small", "default"), ("mid", "default"), ("big", "default"),
    ]
    only, _ = bk.build_plan(_FakeClient(models), "http://x", ["big", "small"], ["off"])
    assert only == [("small", "off"), ("big", "off")]


def test_mode_fields_switch_thinking_off_with_the_field_that_worked_on_lm_studio():
    assert bk.MODE_FIELDS["off"] == {"reasoning_effort": "none"}
    assert bk.MODE_FIELDS["default"] == {}


def test_auc_perfect_chance_and_ties():
    assert bk._auc([80, 90], [40, 50]) == 1.0
    assert bk._auc([50], [50]) == 0.5
    assert bk._auc([40], [90]) == 0.0
    assert bk._auc([], [1]) is None


def test_summary_counts_by_group_and_flags_wrong_off_calls():
    def v(score, domain):
        return {"verdict": {"score": score, "domain_fit": domain}, "secs": 2.0, "completion_tokens": 100, "first_try_valid": True}

    run = {"model": "m", "mode": "off", "target": 4, "jobs": {
        "a:1": v(85, "core"), "a:2": v(60, "off"), "a:3": v(40, "off"), "a:4": {"error": "x", "secs": 1.0, "completion_tokens": 5}}}
    group = {"a:1": "positive", "a:2": "positive", "a:3": "negative", "a:4": "negative"}
    outcome = {"a:1": "applied", "a:2": "saved", "a:3": "irrelevant", "a:4": "irrelevant"}
    s = bk.summarize(run, group, outcome)
    assert s["valid_final"] == 3 and s["done"] == 4 and s["auc"] == 1.0
    assert s["pos_ge70"] == "1/2" and s["neg_ge70"] == "0/1" and s["pos_off"] == "1/2" and s["neg_off"] == "1/1"
    assert s["mean_by_outcome"] == {"applied": 85.0, "irrelevant": 40.0, "saved": 60.0}


def test_golden_sample_is_balanced_so_a_stopped_run_is_still_comparable(tmp_path, monkeypatch):
    jobs = [{"key": f"p{i}", "group": "positive"} for i in range(5)] + [{"key": f"n{i}", "group": "negative"} for i in range(5)]
    jobs.append({"key": "o", "group": "neutral"})
    (tmp_path / "g.json").write_text(json.dumps({"jobs": jobs}))
    monkeypatch.setattr(bk, "GOLDEN", tmp_path / "g.json")
    first6 = bk.load_golden(6)
    assert sum(j["group"] == "positive" for j in first6) == 3 and sum(j["group"] == "negative" for j in first6) == 3
    assert [j["key"] for j in bk.load_golden(6)] == [j["key"] for j in first6]  # deterministic


def test_golden_groups_and_weights():
    assert golden_builder._group("irrelevant") == "negative"
    assert golden_builder._group("okay") == "neutral"
    for outcome in ("offer_declined", "interviewing", "interviewed_rejected", "applied", "rejected", "withdrawn", "saved", "relevant"):
        assert golden_builder._group(outcome) == "positive" and golden_builder.WEIGHT[outcome] > 0
