import json
import sys
from pathlib import Path

import httpx
import pytest
import respx

from job_hunter.config import CandidateProfile, Settings

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import review_with_lm_studio  # noqa: E402
from review_with_lm_studio import (  # noqa: E402
    _eta_suffix,
    _extract_json,
    _format_duration,
    _run_review,
    main,
    resolve_resume,
    review_one,
)

_CONFIG = {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model", "timeout_seconds": 30}


def test_extract_json_handles_surrounding_prose():
    verdict = {"score": 80, "recommended": True, "matches": ["a"], "gaps": ["b"]}
    wrapped = f"Sure, here's my review:\n{json.dumps(verdict)}\nLet me know if you need more."
    assert _extract_json(wrapped) == verdict


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError, match="not valid JSON"):
        _extract_json("I cannot complete this request.")


@respx.mock
def test_review_one_posts_expected_payload_and_parses_verdict():
    verdict = {
        "domain_fit": "core", "seniority_fit": "match", "blockers": [],
        "score": 91, "recommended": True, "matches": ["Python", "ADAS"], "gaps": ["No ROS"],
    }

    def _respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "local-model"
        messages = body["messages"]
        assert messages[0]["role"] == "system"
        assert "Rubric:" in messages[0]["content"]
        assert "Staff Engineer" in messages[1]["content"]
        assert "Acme" in messages[1]["content"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]}
        )

    respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(side_effect=_respond)
    with httpx.Client() as client:
        result = review_one(
            client,
            _CONFIG,
            resume="Experienced Python engineer.",
            rubric="Score 0-100 based on fit.",
            title="Staff Engineer",
            company="Acme",
            location="Detroit, MI",
            url="https://example.com/job",
            description="Build ADAS features.",
        )
    assert result == verdict


def test_negative_limit_is_rejected(monkeypatch, capsys):
    """docs/agent-runtime-audit.md's "input validation" finding -- a bare type=int previously let
    --limit -1 flow into a downstream `to_review[:args.limit]` slice as a silently-valid but
    surprising "all but the last one" instead of a clear command-line error."""
    monkeypatch.setattr(sys, "argv", ["review_with_lm_studio.py", "--limit", "-1"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    assert "non-negative" in capsys.readouterr().err


def test_format_duration_scales_units():
    assert _format_duration(45) == "45s"
    assert _format_duration(125) == "2m05s"
    assert _format_duration(3725) == "1h02m"


def test_eta_suffix_empty_before_any_job_completes():
    assert _eta_suffix(started=0.0, done=0, total=10) == ""


def test_eta_suffix_reports_measured_average_and_remaining(monkeypatch):
    times = iter([100.0])  # one call to time.monotonic() inside _eta_suffix
    monkeypatch.setattr(review_with_lm_studio.time, "monotonic", lambda: next(times))
    # started=0.0, one job done after 100s elapsed -> avg 100s/job, 4 remaining -> ~400s
    suffix = _eta_suffix(started=0.0, done=1, total=5)
    assert suffix == " [avg 1m40s/job, ~6m40s remaining]"


@respx.mock
def test_run_review_writes_progress_log_and_final_summary(tmp_path, monkeypatch):
    """`job-hunter pipeline` runs this whole script as a subprocess with stdout/stderr fully
    buffered until it exits (see pipeline.py's `_run_stage_subprocess`), so `--progress-log` is
    the only way live per-job progress reaches anything tail-able during that kind of run."""
    monkeypatch.setattr(
        review_with_lm_studio, "check_lm_studio", lambda config: (True, "http://fake/v1 -- ok")
    )
    verdict = {
        "domain_fit": "core", "seniority_fit": "match", "blockers": [],
        "score": 88, "recommended": True, "matches": ["Python", "ADAS"], "gaps": ["No ROS"],
    }
    respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]})
    )

    settings = Settings(database_path=tmp_path / "jobs.sqlite3")
    profile = CandidateProfile(resume_path=tmp_path / "resume.txt")
    candidate = {
        "source_key": "acme", "job_id": "42", "company": "Acme", "title": "Staff Engineer",
        "url": "https://example.com/42", "location_raw": "Remote", "content_hash": "hash-1",
        "description": "Build things.",
    }
    progress_log = tmp_path / "runs" / "review.log"

    exit_code = _run_review(
        [candidate], skipped_cached=3, config=_CONFIG, settings=settings, profile=profile,
        resume="Experienced engineer.", rubric="Score 0-100.", progress_log=progress_log,
    )

    assert exit_code == 0
    log_text = progress_log.read_text()
    assert "Starting local LLM review of 1 job(s); 3 already cached." in log_text
    assert "Reviewing [1/1] Acme — Staff Engineer" in log_text
    assert "done [1/1, 0 remaining]: score=88 recommended=True" in log_text
    assert "Reviewed 1 job(s); skipped 3 already-assessed (unchanged) job(s)." in log_text


def test_resolve_resume_prefers_the_newest_dated_resume_over_the_profile_path(tmp_path):
    (tmp_path / "old.md").write_text("profile resume")
    directory = tmp_path / "config" / "resume"
    directory.mkdir(parents=True)
    (directory / "main_resume_2026-05-05.md").write_text("newest resume")
    profile = CandidateProfile(resume_path=Path("old.md"))
    updated, text = resolve_resume(profile, tmp_path)
    assert text == "newest resume"
    assert updated.resume_path == (directory / "main_resume_2026-05-05.md").resolve()
    assert profile.resume_path == Path("old.md")  # the original model is not mutated


def test_resolve_resume_falls_back_to_the_profile_path_and_errors_when_neither_exists(tmp_path):
    (tmp_path / "old.md").write_text("profile resume")
    profile = CandidateProfile(resume_path=Path("old.md"))
    assert resolve_resume(profile, tmp_path)[1] == "profile resume"
    with pytest.raises(FileNotFoundError):
        resolve_resume(CandidateProfile(), tmp_path / "empty")


# ------------------------------------------------------------------ reasoning switch and format retry


def test_reasoning_config_maps_to_request_fields_and_rejects_unknown_values():
    import pytest

    from job_hunter.lm_studio_health import reasoning_fields

    assert reasoning_fields({}) == {} and reasoning_fields({"reasoning": "default"}) == {}
    assert reasoning_fields({"reasoning": "off"}) == {"reasoning_effort": "none"}
    assert reasoning_fields({"reasoning": " LOW "}) == {"reasoning_effort": "low"}
    # a bare `reasoning: off` in YAML parses to the boolean False; that must still switch thinking off
    import yaml

    assert reasoning_fields(yaml.safe_load("reasoning: off")) == {"reasoning_effort": "none"}
    assert reasoning_fields(yaml.safe_load('reasoning: "off"')) == {"reasoning_effort": "none"}
    assert reasoning_fields({"reasoning": True}) == {}
    with pytest.raises(ValueError):
        reasoning_fields({"reasoning": "fast"})


class _Resp:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class _ScriptedClient:
    def __init__(self, answers):
        self.answers, self.bodies = list(answers), []

    def post(self, url, json=None, timeout=0):
        self.bodies.append(json)
        return _Resp(self.answers.pop(0))


_GOOD = ('{"domain_fit":"core","seniority_fit":"match","blockers":[],"matches":["a","b"],"gaps":["c"],"score":80,"recommended":true}')


def _review(client, **config):
    import review_with_lm_studio as r

    return r.review_one(client, {"base_url": "http://x/v1", **config}, resume="R", rubric="rubric", title="T", company="C",
                        location="L", url="u", description="d")


def test_review_sends_thinking_off_when_configured():
    client = _ScriptedClient([_GOOD])
    assert _review(client, reasoning="off")["score"] == 80
    assert client.bodies[0]["reasoning_effort"] == "none"
    plain = _ScriptedClient([_GOOD])
    _review(plain)
    assert "reasoning_effort" not in plain.bodies[0]


def test_review_retries_a_malformed_answer_once_and_strips_think_blocks():
    client = _ScriptedClient(["not json at all", "<think>hmm</think>" + _GOOD])
    assert _review(client)["score"] == 80 and len(client.bodies) == 2


def test_review_gives_up_after_the_second_malformed_answer():
    import pytest

    client = _ScriptedClient(["nope", '{"domain_fit":"core"}'])
    with pytest.raises(ValueError):
        _review(client)
    assert len(client.bodies) == 2


def test_resume_for_review_is_the_master_text_unless_the_view_is_enabled():
    import review_with_lm_studio as r

    text = "# **JANE DOE**\n\njane@example.com | https://example.com\n\n# **SUMMARY**\n\nHello.\n"
    assert r.resume_for_review(text, {}) == text
    assert r.resume_for_review(text, {"resume_view": {"enabled": False}}) == text
    view = r.resume_for_review(text, {"resume_view": {"enabled": True}})
    assert "jane@example.com" not in view and "JANE" not in view and "Hello." in view
