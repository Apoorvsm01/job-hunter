from job_hunter.config import FitConfig
from job_hunter.fit import evaluate_fit, pay_top_usd

CFG = FitConfig(enabled=True)  # defaults: 78/70 with judgments, 85/75 without, $160K pay floor


def _a(score, **facets):
    return {"score": score, **facets}


def test_score_alone_decides_for_assessments_without_judgments_against_the_stricter_bars():
    assert evaluate_fit({}, _a(85), CFG).tier == "top"
    assert evaluate_fit({}, _a(80), CFG).tier == "likely"  # would be a Top pick with judgments
    assert evaluate_fit({}, _a(75), CFG).tier == "likely"
    assert evaluate_fit({}, _a(74), CFG).tier is None
    assert evaluate_fit({}, None, CFG).tier is None


def test_judgments_gate_the_tier():
    core = {"domain_fit": "core", "seniority_fit": "match", "blockers": []}
    assert evaluate_fit({}, _a(85, **core), CFG).tier == "top"
    assert evaluate_fit({}, _a(78, **core), CFG).tier == "top"
    assert evaluate_fit({}, _a(77, **core), CFG).tier == "likely"
    assert evaluate_fit({}, _a(69, **core), CFG).tier is None
    assert evaluate_fit({}, _a(85, **{**core, "domain_fit": "adjacent"}), CFG).tier == "likely"
    assert evaluate_fit({}, _a(85, **{**core, "seniority_fit": "above"}), CFG).tier == "likely"
    assert evaluate_fit({}, _a(85, **{**core, "blockers": ["clearance"]}), CFG).tier == "likely"
    assert evaluate_fit({}, _a(85, **{**core, "domain_fit": "off"}), CFG).tier is None


def test_a_dream_job_reaches_top_at_the_lower_bar_but_only_when_clean():
    core = {"domain_fit": "core", "seniority_fit": "match", "blockers": []}
    assert evaluate_fit({}, _a(72, **core), CFG).tier == "likely"
    d = evaluate_fit({}, _a(72, **core), CFG, is_dream=True)
    assert d.tier == "top" and "dream" in d.reasons
    assert evaluate_fit({}, _a(72, **{**core, "domain_fit": "adjacent"}), CFG, is_dream=True).tier == "likely"
    assert evaluate_fit({}, _a(60, **core), CFG, is_dream=True).tier is None


def test_pay_is_separate_from_fit_and_unknown_is_never_low():
    job = {"salary_max": 138000, "salary_currency": "USD"}
    d = evaluate_fit(job, _a(92, domain_fit="core", seniority_fit="match", blockers=[]), CFG)
    assert d.tier == "top" and d.pay == "low" and d.pay_top == 138000  # best fit, pay below the floor
    assert evaluate_fit({"salary_max": 160000}, None, CFG).pay == "ok"
    assert evaluate_fit({}, None, CFG).pay is None
    assert pay_top_usd({"salary_max": 85, "salary_currency": "USD"}) is None  # hourly rate
    assert pay_top_usd({"salary_max": 200000, "salary_currency": "EUR"}) is None
    assert pay_top_usd({"salary_min": 150000}) == 150000
