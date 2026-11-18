"""
Automated validation of Requirements Traceability Catalog for Step 01.
Verifies completeness of actors, domains, voice modes, service owners, API routes, and test IDs.
"""
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REQ_FILE = REPO_ROOT / "docs" / "requirements" / "requirements-traceability.md"

def test_requirements_file_exists():
    assert REQ_FILE.exists(), f"Requirements catalog file missing: {REQ_FILE}"

def test_actors_coverage():
    content = REQ_FILE.read_text(encoding="utf-8")
    expected_actors = ["ACT-01", "ACT-02", "ACT-03", "ACT-04", "ACT-05", "ACT-06"]
    for actor in expected_actors:
        assert actor in content, f"Actor {actor} not documented in requirements catalog."

def test_core_user_journeys_coverage():
    content = REQ_FILE.read_text(encoding="utf-8")
    assert "Inbound Omnichannel Discovery to Verified Quotation" in content
    assert "Inbound Customer Voice Inquiry with Identity Gate" in content
    assert "Manager Voice Copilot Briefing & Second-Factor Approval" in content
    assert "Checkout, Stock Hold, and Payment Settlement Saga" in content

def test_voice_modes_explicit_requirements():
    content = REQ_FILE.read_text(encoding="utf-8")
    # Verify Customer Voice Mode has OTP verification requirement
    assert "REQ-VOI-01" in content
    assert "REQ-VOI-02" in content
    # Verify Manager Voice Mode has MFA and spoken action restriction
    assert "REQ-VOI-03" in content
    assert "REQ-VOI-04" in content

def test_all_requirements_have_service_owners_apis_tests():
    content = REQ_FILE.read_text(encoding="utf-8")
    # Parse table rows in Section 3
    lines = content.splitlines()
    req_rows = [line for line in lines if line.strip().startswith("| **REQ-")]
    
    assert len(req_rows) >= 30, f"Expected at least 30 requirements, found {len(req_rows)}"
    
    seen_req_ids = set()
    for row in req_rows:
        cols = [c.strip() for c in row.split("|")[1:-1]]
        req_id = re.sub(r"[\*\_]", "", cols[0])
        domain = cols[1]
        actor = cols[2]
        desc = cols[3]
        service_owner = cols[4]
        api_route = cols[5]
        test_id = re.sub(r"[\*\_`]", "", cols[6])
        security_link = cols[7]

        # Verify uniqueness
        assert req_id not in seen_req_ids, f"Duplicate Requirement ID found: {req_id}"
        seen_req_ids.add(req_id)

        # Verify all fields are non-empty
        assert len(domain) > 0, f"{req_id} missing domain"
        assert len(actor) > 0, f"{req_id} missing actor"
        assert len(desc) > 10, f"{req_id} description too short"
        assert len(service_owner) > 0, f"{req_id} missing service owner"
        assert len(api_route) > 0, f"{req_id} missing API contract route"
        assert test_id.startswith("TEST-"), f"{req_id} test ID must start with TEST-, got {test_id}"
        assert len(security_link) > 0, f"{req_id} missing security link"

def test_major_business_domains_covered():
    content = REQ_FILE.read_text(encoding="utf-8")
    expected_prefixes = [
        "REQ-IAM-", "REQ-OMN-", "REQ-VOI-", "REQ-CRM-", "REQ-CAT-", 
        "REQ-QTE-", "REQ-ORD-", "REQ-PAY-", "REQ-INV-", "REQ-LOG-", 
        "REQ-SUP-", "REQ-SCH-", "REQ-AGY-", "REQ-ANL-", "REQ-SEC-"
    ]
    for prefix in expected_prefixes:
        assert prefix in content, f"Domain prefix {prefix} missing from requirements matrix."
