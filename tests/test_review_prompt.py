import pytest
from pydantic import ValidationError

from job_hunter.config import CandidateProfile
from job_hunter.review_prompt import (
    CAP_ADJACENT,
    CAP_BLOCKER,
    CAP_OFF_DOMAIN,
    CAP_SENIORITY,
    MAX_DESCRIPTION_CHARS,
    ModelVerdict,
    apply_caps,
    clean_descriptions,
    domain_definition,
    history_block,
)


def _verdict(**over):
    base = {
        "domain_fit": "core", "seniority_fit": "match", "blockers": [],
        "matches": ["a", "b"], "gaps": ["c"], "score": 88, "recommended": True,
    }
    base.update(over)
    return base


def test_verdict_schema_is_strict_and_keeps_judgments_before_the_score():
    assert list(ModelVerdict.model_fields)[:3] == ["domain_fit", "seniority_fit", "blockers"]
    assert list(ModelVerdict.model_fields)[-2:] == ["score", "recommended"]
    with pytest.raises(ValidationError):
        ModelVerdict.model_validate(_verdict(domain_fit="maybe"))
    with pytest.raises(ValidationError):
        ModelVerdict.model_validate({k: v for k, v in _verdict().items() if k != "domain_fit"})
    assert ModelVerdict.model_validate(_verdict(recommended="false")).recommended is False
    with pytest.raises(ValidationError):
        ModelVerdict.model_validate(_verdict(score=101))


def test_empty_blocker_words_do_not_count_as_blockers():
    v = ModelVerdict.model_validate(_verdict(blockers=["none", " ", "N/A"]))
    assert v.blockers == []


@pytest.mark.parametrize(
    ("over", "cap"),
    [
        ({"domain_fit": "off"}, CAP_OFF_DOMAIN),
        ({"domain_fit": "adjacent"}, CAP_ADJACENT),
        ({"blockers": ["TS/SCI clearance required"]}, CAP_BLOCKER),
        ({"seniority_fit": "above"}, CAP_SENIORITY),
        ({"seniority_fit": "below"}, CAP_SENIORITY),
    ],
)
def test_caps_clamp_the_score_and_say_so(over, cap):
    out = apply_caps(_verdict(score=92, **over), threshold=75)
    assert out["score"] == min(cap, 92)
    assert any(f"capped at {cap}" in g and "model scored 92" in g for g in out["gaps"])


def test_strictest_cap_wins_and_everything_that_set_it_is_named():
    out = apply_caps(_verdict(score=90, domain_fit="off", blockers=["x"], seniority_fit="above"), threshold=75)
    assert out["score"] == CAP_OFF_DOMAIN
    assert out["recommended"] is False


def test_a_clean_core_match_is_untouched_and_a_low_score_is_never_raised():
    clean = apply_caps(_verdict(), threshold=75)
    assert clean["score"] == 88 and clean["gaps"] == ["c"] and clean["recommended"] is True
    low = apply_caps(_verdict(score=30, domain_fit="off"), threshold=75)
    assert low["score"] == 30 and low["gaps"] == ["c"]


def test_recommended_is_rederived_from_the_clamped_score_and_blockers():
    assert apply_caps(_verdict(score=80, domain_fit="adjacent"), threshold=75)["recommended"] is False
    assert apply_caps(_verdict(score=80, domain_fit="adjacent"), threshold=70)["recommended"] is True
    assert apply_caps(_verdict(score=95, blockers=["license"]), threshold=75)["recommended"] is False


def test_domain_definition_comes_from_the_profile_and_judges_technology_not_function():
    profile = CandidateProfile(target_domains=["ADAS", "robotics"], strong_relevance_terms=["lidar"])
    text = domain_definition(profile)
    assert "ADAS, robotics" in text and "lidar" in text
    assert "not the job function" in text and "off:" in text


def test_history_block_orders_by_strength_dedupes_and_is_deterministic():
    apps = [
        {"status": "saved", "title": "Test Eng", "company": "A"},
        {"status": "offer", "title": "AV Test Engineer", "company": "GM"},
        {"status": "interviewing", "title": "Core Integration Engineer", "company": "Ford"},
        {"status": "applied", "title": "AV Test Engineer", "company": "GM"},  # duplicate, dropped
        {"status": "withdrawn", "title": "Ignored", "company": "Z"},
    ]
    fb = [
        {"label": "irrelevant", "title": "Silicon Validation Engineer", "company": "Apple"},
        {"label": "irrelevant", "title": "Test Eng", "company": "A"},  # already pursued, not "rejected"
        {"label": "okay", "title": "Fine", "company": "B"},
    ]
    text = history_block(apps, fb)
    assert text == history_block(list(reversed(apps)), list(reversed(fb)))
    assert text.index("received an offer") < text.index("interviewed") < text.index("saved")
    assert text.count("AV Test Engineer") == 1 and "Ignored" not in text and "Fine" not in text
    assert "Silicon Validation Engineer (Apple)" in text and "marked irrelevant" in text
    assert "never copy a requirement" in text
    assert history_block([], []) == ""


def test_history_block_caps_its_size():
    apps = [{"status": "applied", "title": f"Role {i}", "company": "C"} for i in range(40)]
    assert history_block(apps, [], max_pursued=5).count("\n- ") == 5


def test_clean_descriptions_strips_recurring_company_copy_and_keeps_head_and_tail():
    boiler = "We are an equal opportunity employer and value diversity across every team here."
    cands = [
        {"source_key": "s", "job_id": str(i), "description": f"Role {i} builds sensors.\n{boiler}"}
        for i in range(6)
    ]
    cleaned = clean_descriptions(cands)
    assert cleaned[("s", "0")] == "Role 0 builds sensors."
    long = {"source_key": "t", "job_id": "x", "description": "HEAD " + "m" * 20000 + " REQUIREMENTS-AT-END"}
    out = clean_descriptions([long])[("t", "x")]
    assert out.startswith("HEAD") and out.endswith("REQUIREMENTS-AT-END")
    assert len(out) < MAX_DESCRIPTION_CHARS + 60 and "omitted" in out
    short = {"source_key": "u", "job_id": "y", "description": "tiny"}
    assert clean_descriptions([short])[("u", "y")] == "tiny"
