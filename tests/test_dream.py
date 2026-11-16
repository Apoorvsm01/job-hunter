from job_hunter.config import DreamConfig, RadarConfig
from job_hunter.dream import evaluate_dream

CFG = DreamConfig(
    companies=["Waymo", "Google DeepMind"],
    title_terms=["lead", "supervisor", "principal", "staff"],
    weak_title_terms=["senior"],
    min_salary_usd=160000,
)


def job(**kw):
    base = {"company": "Acme", "source_key": "acme", "title": "Engineer"}
    return {**base, **kw}


def test_disabled_by_default():
    assert not RadarConfig().dream.enabled
    assert not evaluate_dream(job(title="Senior Lead"), DreamConfig()).is_dream
    assert not evaluate_dream(job(title="Senior Lead"), None).is_dream


def test_title_terms_match_whole_words_only():
    assert evaluate_dream(job(title="Vehicle Calibration & Test Supervisor"), CFG).reasons == ("title: supervisor",)
    assert evaluate_dream(job(title="Autonomy Systems Integration Lead"), CFG).is_dream
    assert evaluate_dream(job(title="Tech-Lead, Perception"), CFG).is_dream
    for t in ("Leadership Program Intern", "Misleading Title Engineer", "Seniority Analyst"):
        assert not evaluate_dream(job(title=t), CFG).is_dream


def test_staff_is_a_whole_word_title_term():
    assert evaluate_dream(job(title="Staff Perception Engineer"), CFG).reasons == ("title: staff",)
    assert not evaluate_dream(job(title="Staffing Coordinator"), CFG).is_dream


def test_company_matches_name_or_source_key_case_insensitively():
    assert evaluate_dream(job(company="WAYMO"), CFG).reasons == ("company: Waymo",)
    assert evaluate_dream(job(company="Google", source_key="google deepmind"), CFG).is_dream
    assert not evaluate_dream(job(company="Waymo Fleet Services"), CFG).is_dream


def test_salary_uses_top_of_range_usd_only_and_missing_never_disqualifies():
    assert evaluate_dream(job(salary_min=128470, salary_max=208770), CFG).reasons == ("salary: $208,770",)
    assert evaluate_dream(job(salary_min=170000), CFG).is_dream
    assert not evaluate_dream(job(salary_min=100000, salary_max=159999), CFG).is_dream
    assert not evaluate_dream(job(salary_max=300000, salary_currency="EUR"), CFG).is_dream
    assert evaluate_dream(job(title="Supervisor"), CFG).is_dream  # no salary, still dream by title


def test_reasons_list_every_matching_rule():
    d = evaluate_dream(job(company="Waymo", title="Principal Engineer", salary_max=200000), CFG)
    assert d.reasons == ("company: Waymo", "title: principal", "salary: $200,000")


def test_weak_title_term_alone_is_dream_ish_and_any_strong_rule_outranks_it():
    weak = evaluate_dream(job(title="Senior Controls Engineer"), CFG)
    assert (weak.tier, weak.is_dream, weak.is_weak, weak.reasons) == ("weak", False, True, ("title: senior",))
    strong = evaluate_dream(job(title="Senior Staff Engineer"), CFG)
    assert strong.tier == "dream" and strong.reasons == ("title: staff",)
    assert evaluate_dream(job(title="Senior Engineer", salary_max=200000), CFG).tier == "dream"
    assert evaluate_dream(job(title="Seniority Analyst"), CFG).tier is None


def test_company_matches_a_sub_brand_from_googles_employer_label():
    cfg = DreamConfig(companies=["Google DeepMind"])
    header = "Senior Lab Operations Manager, DeepMindshareShare ... corporate_fareDeepMindplaceMountain View, CA"
    assert evaluate_dream(job(company="Google", source_key="google", description=header), cfg).is_dream
    google = "Software Engineer ... corporate_fareGooglePlaceplaceX corporate_fareGoogleplaceMountain View"
    assert not evaluate_dream(job(company="Google", source_key="google", description=google), cfg).is_dream
    assert evaluate_dream(job(company="Google", description=header), DreamConfig(companies=["deepmind"])).is_dream


def test_title_exclusions_cancel_title_rules_only():
    cfg = DreamConfig(
        companies=["Waymo"], title_terms=["manager"], weak_title_terms=["senior"],
        title_exclusions=["project manager", "product manager", "program manager"],
        min_salary_usd=160000,
    )
    assert evaluate_dream(job(title="Manager, System Software Validation & Verification"), cfg).is_dream
    for t in ("Technical Program Manager", "Senior Product Manager, Maps", "Project Manager, Sourcing"):
        assert evaluate_dream(job(title=t), cfg).tier is None, t
    # company / salary still count for an excluded title
    assert evaluate_dream(job(title="Product Manager", company="Waymo"), cfg).reasons == ("company: Waymo",)
    assert evaluate_dream(job(title="Product Manager", salary_max=200000), cfg).reasons == ("salary: $200,000",)


def test_level_rule_uses_the_highest_stated_level_for_that_source_only():
    from job_hunter.config import LevelRule

    cfg = DreamConfig(levels={"ford": LevelRule(pattern=r"fordcareers\.co/LL(\d+)", min=6, label="LL")})
    ll = lambda *n: " ".join(f"click https://fordcareers.co/LL{x}" for x in n)  # noqa: E731
    assert evaluate_dream(job(source_key="ford", description=ll(6)), cfg).reasons == ("level: LL6",)
    assert evaluate_dream(job(source_key="ford", description=ll(5, 7)), cfg).reasons == ("level: LL7",)  # top of range
    assert not evaluate_dream(job(source_key="ford", description=ll(5)), cfg).is_dream
    assert not evaluate_dream(job(source_key="ford", description="no level stated"), cfg).is_dream
    assert not evaluate_dream(job(source_key="other", description=ll(9)), cfg).is_dream


def test_level_rule_pattern_needs_exactly_one_capture_group():
    import pytest
    from pydantic import ValidationError

    from job_hunter.config import LevelRule

    with pytest.raises(ValidationError):
        LevelRule(pattern=r"LL\d+", min=6)
