"""
Automated validation of Architecture Consistency for Step 01.
Verifies ADRs, C4 Mermaid diagrams, DFD/STRIDE trust boundaries, and alignment with domain services.
"""
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ADR_DIR = REPO_ROOT / "docs" / "adr"
ARCH_DIR = REPO_ROOT / "docs" / "architecture"
RISK_FILE = REPO_ROOT / "security" / "risk-register.md"

def test_all_10_adrs_exist_and_accepted():
    expected_adrs = [
        "ADR-001-modular-deterministic-backend.md",
        "ADR-002-postgresql-truth-and-rls.md",
        "ADR-003-redis-ephemerality.md",
        "ADR-004-three-path-ai-execution.md",
        "ADR-005-dual-mode-voice-architecture.md",
        "ADR-006-authorization-and-tenant-isolation.md",
        "ADR-007-temporal-ownership-n8n-peripheral.md",
        "ADR-008-s3-object-storage-and-retention.md",
        "ADR-009-model-gateway-and-provider-isolation.md",
        "ADR-010-security-controls-and-evidence-structure.md",
    ]
    for adr in expected_adrs:
        adr_path = ADR_DIR / adr
        assert adr_path.exists(), f"Missing ADR file: {adr}"
        content = adr_path.read_text(encoding="utf-8")
        assert "## Status" in content
        assert "Accepted" in content
        assert "## Decision" in content
        assert "## Invariants Enforced" in content

def test_c4_mermaid_diagrams_exist():
    expected_diagrams = [
        "context.mmd",
        "containers.mmd",
        "components.mmd",
        "trust-boundaries.mmd"
    ]
    for diag in expected_diagrams:
        diag_path = ARCH_DIR / diag
        assert diag_path.exists(), f"Missing Mermaid diagram: {diag}"
        content = diag_path.read_text(encoding="utf-8")
        assert "flowchart" in content or "graph" in content

def test_c4_container_diagram_includes_key_containers():
    containers_content = (ARCH_DIR / "containers.mmd").read_text(encoding="utf-8")
    assert "FastAPICore" in containers_content
    assert "VoiceGateway" in containers_content
    assert "ModelGatewayService" in containers_content
    assert "TemporalEngine" in containers_content
    assert "PeripheralN8N" in containers_content
    assert "PostgresDB" in containers_content
    assert "RedisInstance" in containers_content
    assert "S3Storage" in containers_content

def test_trust_boundaries_diagram_covers_all_8_threat_domains():
    tb_content = (ARCH_DIR / "trust-boundaries.mmd").read_text(encoding="utf-8")
    assert "Trust Boundary 1: Customer Inbound & Voice Media" in tb_content
    assert "Trust Boundary 2: Manager Voice Copilot & Privileged Actions" in tb_content
    assert "Trust Boundary 3: External Provider Webhooks" in tb_content
    assert "Trust Boundary 4: AI Tool Execution Boundary" in tb_content
    assert "Trust Boundary 5: RAG & Document Knowledge Boundary" in tb_content
    assert "Trust Boundary 6: Payment Events & Financial Transactions" in tb_content
    assert "Trust Boundary 7: Stock Ledger & Inventory Reservation" in tb_content
    assert "Trust Boundary 8: Approval Hierarchy & Quote Discounts" in tb_content

def test_risk_register_covers_stride_and_launch_blockers():
    assert RISK_FILE.exists(), f"Risk register missing: {RISK_FILE}"
    content = RISK_FILE.read_text(encoding="utf-8")
    assert "RSK-01" in content
    assert "RSK-12" in content
    assert "YES (P0)" in content
    # Verify launch blockers section
    assert "P0 LAUNCH BLOCKERS SUMMARY" in content
