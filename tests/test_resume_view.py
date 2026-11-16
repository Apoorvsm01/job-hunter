from job_hunter.resume_view import review_resume_view

RESUME = """# **JANE Q DOE**

jane@example.com | [\\+1-555-010-0199](about:blank) | https://www.linkedin.com/in/janedoe | https://github.com/janedoe

# **SUMMARY**

Systems engineer with **ADAS** testing experience.

# **PROFESSIONAL EXPERIENCE**

## **Test Engineer\tSept 2025 – To Present**

### *Acme Motors, MI, US*

- Led validation of lane-keeping features.
- Wrote the test plan.

## **Process Engineer Intern\tMay 2016 – Aug 2016**

### *Widget Co, AZ, US*

- Mapped a bottling line and wrote three work instructions for the night shift.

# **STUDENT TEAM**

## **Suspension Lead\tAug 2012 – Aug 2014**

### *Race Team, Mumbai, India*

- Designed the front suspension.

# **PUBLICATIONS**

## **A Paper on Edge Cases**

### *Some Symposium 2026 | DOI: 10.1000/xyz123*

- Contributed the detector.
"""


def test_header_contact_details_and_urls_are_removed_but_the_content_stays():
    view = review_resume_view(RESUME)
    for gone in ("JANE", "jane@example.com", "555", "linkedin", "github.com", "DOI", "about:blank", "**"):
        assert gone not in view
    assert view.startswith("# SUMMARY") or view.startswith("# **SUMMARY") or "SUMMARY" in view.splitlines()[0]
    assert "Systems engineer with ADAS testing experience." in view
    assert "Led validation of lane-keeping features." in view
    assert "A Paper on Edge Cases" in view and "Contributed the detector." in view


def test_tabs_become_separators():
    assert "Test Engineer | Sept 2025 – To Present" in review_resume_view(RESUME)


def test_compact_sections_and_entries_shrink_to_one_line():
    view = review_resume_view(RESUME, compact_sections=["student team"], compact_entry_terms=["Intern"])
    assert "- Process Engineer Intern | May 2016 – Aug 2016 | Widget Co, AZ, US" in view
    assert "bottling line" not in view
    assert "- Suspension Lead | Aug 2012 – Aug 2014 | Race Team, Mumbai, India" in view
    assert "front suspension" not in view
    assert "Led validation of lane-keeping features." in view  # main role untouched
    assert len(view) < len(review_resume_view(RESUME))


def test_without_configuration_nothing_is_condensed():
    view = review_resume_view(RESUME)
    assert "bottling line" in view and "front suspension" in view


def test_a_resume_without_a_name_header_is_kept_whole():
    text = "# **SUMMARY**\n\nHello.\n\n# **SKILLS**\n\nPython\n"
    view = review_resume_view(text)
    assert "Hello." in view and "Python" in view


def test_the_original_text_is_not_modified():
    before = RESUME
    review_resume_view(before, compact_sections=["student team"])
    assert before == RESUME
