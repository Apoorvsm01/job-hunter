import json
from datetime import date

import pytest

from job_hunter.targets import (
    Target,
    TargetNotFound,
    export_target_brief,
    find_target,
    load_targets,
    render_target_brief,
)

TODAY = date(2026, 10, 27)


def _row(key="acme-health", rank=1, **over):
    row = {
        "rank": rank, "key": key, "company": "Acme Health, Inc.", "industries": "Digital Health",
        "website": "https://acme.example", "description": "Voice AI for clinics.",
        "contact": {"first_name": "Jane", "last_name": "Doe", "title": "CEO", "email": "jane@example.com"},
        "score": 90, "fit": "Voice and dashboards.", "lead_story": "timing_perception", "chicago": True,
    }
    row.update(over)
    return row


@pytest.fixture
def targets_dir(tmp_path):
    directory = tmp_path / "data" / "targets"
    directory.mkdir(parents=True)
    (directory / "a.json").write_text(json.dumps({"targets": [_row(), _row("b-co", 2, company="B Co")]}))
    return directory


def test_load_targets_orders_by_rank_and_drops_duplicate_keys(targets_dir):
    (targets_dir / "z.json").write_text(json.dumps({"targets": [_row("acme-health", 9, company="Dup")]}))
    targets = load_targets(targets_dir)
    assert [t.key for t in targets] == ["acme-health", "b-co"]
    assert targets[0].company == "Acme Health, Inc."


def test_missing_directory_is_an_empty_list(tmp_path):
    assert load_targets(tmp_path / "nope") == []


def test_find_target_raises_for_an_unknown_key(targets_dir):
    with pytest.raises(TargetNotFound):
        find_target(load_targets(targets_dir), "missing")


def test_brief_first_line_is_the_role_and_it_names_the_contact_and_story():
    text = render_target_brief(Target.model_validate(_row()), today=TODAY)
    assert text.startswith("Product Designer\n")
    assert "Company: Acme Health, Inc." in text and "Contact: Jane Doe, CEO" in text
    assert "Timing and perception (Woven)" in text and "jane@example.com" not in text


def test_export_writes_a_sanitized_file_and_the_matching_prompts(tmp_path):
    target = Target.model_validate(_row())
    out = tmp_path / "data" / "output"
    resume = export_target_brief(target, "resume", project_root=tmp_path, output_root=out, today=TODAY)
    assert resume.relative_path == "data/output/Acme_Health_Inc/JD_Acme_Health_Inc_Product_Designer_2026-10-27.txt"
    assert resume.created and resume.prompt == f"Use the resume-generator skill on {resume.relative_path}"
    cover = export_target_brief(target, "cover", project_root=tmp_path, output_root=out, today=TODAY)
    assert not cover.created and cover.relative_path == resume.relative_path
    assert cover.prompt.startswith(f"Use the outreach-writer skill on {resume.relative_path}")
    assert "Jane Doe (CEO) at Acme Health, Inc." in cover.prompt and "jane@example.com" not in cover.prompt
