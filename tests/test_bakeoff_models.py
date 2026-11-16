import csv
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


# ------------------------------------------------------------------ completeness, publishing, privacy


def _golden_jobs():
    return [
        {"key": "acme:1", "group": "positive", "outcome": "applied", "company": "Acme Motors", "title": "Secret Role One"},
        {"key": "acme:2", "group": "positive", "outcome": "saved", "company": "Acme Motors", "title": "Secret Role Two"},
        {"key": "zeta:3", "group": "negative", "outcome": "irrelevant", "company": "Zeta Chips", "title": "Chip Verifier"},
        {"key": "zeta:4", "group": "negative", "outcome": "irrelevant", "company": "Zeta Chips", "title": "Chip Tester"},
    ]


def _job(score, domain="core"):
    return {"verdict": {"score": score, "domain_fit": domain}, "secs": 3.0, "completion_tokens": 50, "first_try_valid": True}


def _write_run_dir(tmp_path, golden, runs, name="2026-01-01-T-00-00-00"):
    out = tmp_path / name
    (out / "runs").mkdir(parents=True)
    meta = bk.run_meta(golden, context_length=8192, note="test rig")
    meta["created_at"] = "2026-01-01T00:00:00+00:00"
    (out / "meta.json").write_text(json.dumps(meta))
    for run in runs:
        (out / "runs" / f"{run['model']}__{run['mode']}.json").write_text(json.dumps(run))
    return out


def test_a_run_that_stopped_before_finishing_is_not_complete():
    assert bk.is_complete({"jobs": {"a": {}, "b": {}}}, 2)
    assert not bk.is_complete({"jobs": {"a": {}}}, 2)
    assert not bk.is_complete({"jobs": {"a": {}, "b": {}}, "stopped_reason": "run budget"}, 2)


def test_golden_id_changes_with_the_set_and_ignores_order():
    g = _golden_jobs()
    assert bk.golden_id(g) == bk.golden_id(list(reversed(g)))
    assert bk.golden_id(g) != bk.golden_id(g[:3])
    changed = [dict(g[0], outcome="rejected"), *g[1:]]
    assert bk.golden_id(g) != bk.golden_id(changed)


def test_report_lists_unfinished_runs_apart_with_no_quality_numbers(tmp_path):
    g = _golden_jobs()
    full = {"model": "fast", "mode": "off", "target": 4, "jobs": {"acme:1": _job(80), "acme:2": _job(75), "zeta:3": _job(20, "off"), "zeta:4": _job(30, "off")}}
    partial = {"model": "slow", "mode": "default", "target": 4, "stopped_reason": "run budget", "jobs": {"acme:1": _job(99), "zeta:3": _job(1, "off")}}
    out = _write_run_dir(tmp_path, g, [full, partial])
    bk.write_report(out, g, [("fast", "off"), ("slow", "default")])
    text = (out / "report.md").read_text()
    assert "EXCLUDED from the comparison" in text
    ranked, _, excluded = text.partition("EXCLUDED from the comparison")
    assert "| fast | off |" in ranked and "| slow | default |" not in ranked
    assert "| slow | default | 2/4 |" in excluded
    assert "slow" not in (out / "summary.csv").read_text()


def test_publish_writes_aggregates_only_and_never_a_company_or_title(tmp_path, monkeypatch):
    g = _golden_jobs()
    full = {"model": "fast", "mode": "off", "target": 4, "jobs": {"acme:1": _job(80), "acme:2": _job(75), "zeta:3": _job(20, "off"), "zeta:4": _job(30, "off")}}
    partial = {"model": "slow", "mode": "default", "target": 4, "stopped_reason": "run budget", "jobs": {"acme:1": _job(99)}}
    out = _write_run_dir(tmp_path, g, [full, partial])
    monkeypatch.setattr(bk, "GOLDEN", tmp_path / "golden.json")
    (tmp_path / "golden.json").write_text(json.dumps({"jobs": g}))
    monkeypatch.setattr(bk, "RESULTS_CSV", tmp_path / "docs" / "results.csv")
    monkeypatch.setattr(bk, "RESULTS_MD", tmp_path / "docs" / "RESULTS.md")
    assert bk.publish([out], bk.load_golden(None)) == 0
    published = (tmp_path / "docs" / "results.csv").read_text() + (tmp_path / "docs" / "RESULTS.md").read_text()
    for private in ("Acme", "Zeta", "Secret Role", "Chip Verifier", "acme:1", "zeta:3"):
        assert private not in published
    rows = list(csv.DictReader((tmp_path / "docs" / "results.csv").read_text().splitlines()))
    by = {(r["model"], r["mode"]): r for r in rows}
    assert by[("fast", "off")]["status"] == "complete" and by[("fast", "off")]["auc"] == "1.0"
    assert by[("slow", "default")]["status"] == "did-not-finish" and by[("slow", "default")]["auc"] == ""
    assert by[("fast", "off")]["hardware_note"] == "test rig"
    assert "Did not finish inside the time budget" in published


def test_publish_is_append_only_and_idempotent(tmp_path, monkeypatch):
    g = _golden_jobs()
    run = {"model": "fast", "mode": "off", "target": 4, "jobs": {"acme:1": _job(80), "acme:2": _job(75), "zeta:3": _job(20, "off"), "zeta:4": _job(30, "off")}}
    out = _write_run_dir(tmp_path, g, [run])
    monkeypatch.setattr(bk, "RESULTS_CSV", tmp_path / "r.csv")
    monkeypatch.setattr(bk, "RESULTS_MD", tmp_path / "r.md")
    bk.publish([out], g)
    first = (tmp_path / "r.csv").read_text()
    bk.publish([out], g)
    assert (tmp_path / "r.csv").read_text() == first


def test_publish_refuses_when_the_golden_set_changed_since_the_run(tmp_path):
    g = _golden_jobs()
    out = _write_run_dir(tmp_path, g, [])
    import pytest

    with pytest.raises(SystemExit):
        bk.publish([out], g[:3])


def test_published_results_never_contain_a_golden_company_or_title():
    """Like the owner-PII test: skips without a local golden set; fails if any tracked bake-off doc leaks a real posting."""
    golden = Path("data/golden/golden_jobs.json")
    if not golden.exists():
        import pytest

        pytest.skip("no local golden set")
    jobs = json.loads(golden.read_text())["jobs"]
    published = "\n".join(p.read_text() for p in Path("docs/bakeoff").glob("*") if p.is_file()) if Path("docs/bakeoff").exists() else ""
    for j in jobs:
        title = (j["title"] or "").strip()
        assert j["key"] not in published
        if len(title) > 12:
            assert title not in published, "a golden job title leaked into docs/bakeoff"
