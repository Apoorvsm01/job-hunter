"""Every adapter that builds its own `JobDetail` keeps the rest of its detail payload in
`extras` (extras.py) -- everything except the text already stored as the description.

Each test drives one adapter's real `fetch_detail` with a stand-in response carrying that
adapter's payload shape, so the assertion is on what is kept, not on HTTP plumbing."""

import json
from types import SimpleNamespace

import pytest

from job_hunter.adapters import apple as apple_module
from job_hunter.adapters import brose as brose_module
from job_hunter.adapters import csod as csod_module
from job_hunter.adapters import successfactors_rmk_v2 as sf2_module
from job_hunter.adapters import ultipro as ultipro_module
from job_hunter.adapters.apple import AppleAdapter
from job_hunter.adapters.bosch import BoschAdapter
from job_hunter.adapters.brose import BroseAdapter
from job_hunter.adapters.csod import CsodAdapter
from job_hunter.adapters.eightfold import EightfoldAdapter
from job_hunter.adapters.paycom import PaycomAdapter
from job_hunter.adapters.paylocity import PaylocityAdapter
from job_hunter.adapters.successfactors_rmk_v2 import SuccessFactorsRmkV2Adapter
from job_hunter.adapters.ultipro import UltiProAdapter
from job_hunter.config import CollectionConfig, CompanyConfig
from job_hunter.models import JobSummary


def _summary(raw=None):
    return JobSummary(source_key="x", source_platform="x", company="X", job_id="1", title="T",
                      url="https://example.com/job/1", raw=raw or {})


async def _detail(cls, config, *, payload=None, text=None, raw=None, monkeypatch=None):
    company = CompanyConfig(key="x", company="X", adapter="x", config=config)
    adapter = cls(company, None, CollectionConfig(max_retries=0))

    async def fake_request(self, method, url, **kwargs):
        return SimpleNamespace(json=lambda: payload, text=text if text is not None else json.dumps(payload))

    monkeypatch.setattr(cls, "request", fake_request)
    return await adapter.fetch_detail(_summary(raw))


@pytest.mark.asyncio
async def test_eightfold_keeps_the_rest_of_the_position_record(monkeypatch):
    payload = {"data": {"jobDescription": "Build.", "department": "Eng", "empty": None, "name": "ADAS"}}
    d = await _detail(EightfoldAdapter, {"detail_url": "https://x/d"}, payload=payload, monkeypatch=monkeypatch)
    assert d.description == "Build." and d.extras == {"department": "Eng", "name": "ADAS"}


@pytest.mark.asyncio
async def test_bosch_keeps_the_job_ad_record_but_not_the_section_texts(monkeypatch):
    payload = [{"refNumber": "R1", "contractType": "FT",
                "jobAd": {"language": "en", "sections": {"jobDescription": {"text": "Build ADAS."}}}}]
    d = await _detail(BoschAdapter, {"detail_url": "https://x/d", "api_key": "k"},
                      payload=payload, raw={"refNumber": "R1"}, monkeypatch=monkeypatch)
    assert d.description == "Build ADAS."
    assert d.extras == {"refNumber": "R1", "contractType": "FT", "jobAd": {"language": "en"}}


@pytest.mark.asyncio
async def test_apple_keeps_the_job_record_minus_description_and_summary(monkeypatch):
    job = {"description": "Do things.", "jobSummary": "S", "team": {"teamName": "Hardware"}, "locations": []}
    monkeypatch.setattr(apple_module, "_extract_hydration_data",
                        lambda text: {"loaderData": {"jobDetails": {"jobsData": job}}})
    d = await _detail(AppleAdapter, {}, payload={}, text="<html/>", monkeypatch=monkeypatch)
    assert d.description == "Do things." and d.extras == {"team": {"teamName": "Hardware"}}


@pytest.mark.asyncio
async def test_csod_keeps_the_json_ld_posting_minus_the_description(monkeypatch):
    posting = {"Description": "<p>D</p>", "DatePosted": "2026-10-01", "JobCategory": "Engineering"}
    monkeypatch.setattr(csod_module, "extract_job_posting_ld", lambda text: posting)
    d = await _detail(CsodAdapter, {}, payload={}, text="<html/>", monkeypatch=monkeypatch)
    assert d.extras == {"DatePosted": "2026-10-01", "JobCategory": "Engineering"}


@pytest.mark.asyncio
async def test_paycom_parses_google_job_json_so_its_fields_survive(monkeypatch):
    async def token(self, url):
        return "t"

    monkeypatch.setattr(PaycomAdapter, "_fetch_token", token)
    google = json.dumps({"datePosted": "2026-10-01", "employmentType": "FULL_TIME", "description": "dup"})
    payload = {"jobPosting": {"description": "D", "qualifications": "Q", "department": "Eng", "googleJobJson": google}}
    d = await _detail(PaycomAdapter, {"detail_api_url": "https://x/{id}"}, payload=payload, monkeypatch=monkeypatch)
    assert d.extras == {"department": "Eng",
                        "googleJobJson": {"datePosted": "2026-10-01", "employmentType": "FULL_TIME"}}


@pytest.mark.asyncio
async def test_ultipro_keeps_the_opportunity_record_minus_the_description(monkeypatch):
    body = ultipro_module._DETAIL_MARKER + json.dumps({"Description": "D", "JobCategoryName": "Eng", "Id": "9"})
    d = await _detail(UltiProAdapter, {}, payload={}, text=f"x {body}", monkeypatch=monkeypatch)
    assert d.description == "D" and d.extras == {"JobCategoryName": "Eng", "Id": "9"}


@pytest.mark.asyncio
async def test_brose_keeps_the_json_ld_posting_minus_the_body_fields(monkeypatch):
    posting = {"description": "d", "responsibilities": "r", "title": "Engineer", "hiringOrganization": {"name": "Brose"},
               "datePosted": "10/01/2026", "jobLocation": {"address": {"addressRegion": "MI", "addressCountry": "US"}}}
    monkeypatch.setattr(brose_module, "extract_job_posting_ld", lambda text: posting)
    d = await _detail(BroseAdapter, {}, payload={}, text="<html/>", monkeypatch=monkeypatch)
    assert d.extras["title"] == "Engineer" and d.extras["hiringOrganization"] == {"name": "Brose"}
    assert "description" not in d.extras and "responsibilities" not in d.extras


@pytest.mark.asyncio
async def test_successfactors_v2_keeps_the_other_labelled_tokens(monkeypatch):
    monkeypatch.setattr(sf2_module, "_parse_job_layout_tokens",
                        lambda text: {"job description": "D", "job field": "Engineering", "entry level": "Professional"})
    d = await _detail(SuccessFactorsRmkV2Adapter, {}, payload={}, text="<html/>", monkeypatch=monkeypatch)
    assert d.description == "D" and d.extras == {"job field": "Engineering", "entry level": "Professional"}


@pytest.mark.asyncio
async def test_paylocity_keeps_every_other_labelled_section(monkeypatch):
    html = (
        '<div class="job-listing-header">Description</div><div>Build things</div>'
        '<div class="job-listing-header">Requirements</div><div>5 years</div>'
        '<div class="job-listing-header">Job Type</div><div>Full-Time</div>'
        '<div class="job-listing-header">Location</div><div>Remote</div>'
    )
    d = await _detail(PaylocityAdapter, {}, payload={}, text=html, monkeypatch=monkeypatch)
    assert d.employment_type == "Full-Time"
    assert d.extras == {"Job Type": "Full-Time", "Location": "Remote"}
