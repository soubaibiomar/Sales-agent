"""
Tests for Restricted Peripheral n8n Security Barrier (Invariant 7 & ADR-007).
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
import pytest
import time
import json
from src.backend.integrations.n8n import (
    N8NIntegrationGateway,
    N8NSecurityViolationError
)


def test_n8n_cannot_mutate_commercial_state():
    """
    Verifies that Invariant 7 / ADR-007 is strictly enforced:
    n8n peripheral service identity is blocked with N8NSecurityViolationError
    when attempting any commercial or financial mutation.
    """
    prohibited_actions = [
        "quotes:approve",
        "quotes:reject",
        "orders:mark_paid",
        "orders:cancel",
        "payments:refund",
        "inventory:adjust",
        "prices:modify",
        "po:approve"
    ]

    for action in prohibited_actions:
        with pytest.raises(N8NSecurityViolationError) as exc_info:
            N8NIntegrationGateway.validate_peripheral_action(
                role="peripheral_integration",
                action=action
            )
        assert "Invariant 7 Violation" in str(exc_info.value)
        assert action in str(exc_info.value)


def test_n8n_allows_legitimate_peripheral_actions():
    """
    Verifies that non-commercial read/notification actions are permitted for n8n.
    """
    allowed_actions = [
        "leads:enrich_summary",
        "notifications:dispatch_sync",
        "social:log_campaign_click",
        "surveys:record_response"
    ]

    for action in allowed_actions:
        result = N8NIntegrationGateway.validate_peripheral_action(
            role="peripheral_integration",
            action=action
        )
        assert result is True


def test_internal_admin_can_execute_actions():
    """
    Verifies that non-peripheral roles (e.g. tenant_admin, manager) are not blocked by the n8n barrier.
    """
    assert N8NIntegrationGateway.validate_peripheral_action(
        role="tenant_admin",
        action="quotes:approve"
    ) is True


def test_hmac_webhook_signature_and_replay_protection():
    """
    Verifies HMAC-SHA256 signature verification and replay rejection when timestamp is older than 300s.
    """
    secret = "test_webhook_secret_key_12345"
    payload = json.dumps({"event": "lead.created", "lead_id": "ld-99"}).encode("utf-8")
    now_ts = int(time.time())

    # 1. Valid fresh signature
    sig = N8NIntegrationGateway.generate_signature(secret, payload, now_ts)
    assert N8NIntegrationGateway.verify_signature(secret, payload, sig, now_ts) is True

    # 2. Tampered payload
    tampered = json.dumps({"event": "lead.created", "lead_id": "ld-TAMPERED"}).encode("utf-8")
    assert N8NIntegrationGateway.verify_signature(secret, tampered, sig, now_ts) is False

    # 3. Wrong secret
    assert N8NIntegrationGateway.verify_signature("wrong_secret", payload, sig, now_ts) is False

    # 4. Replay attack: timestamp older than 300s (e.g. 350s ago)
    old_ts = now_ts - 350
    old_sig = N8NIntegrationGateway.generate_signature(secret, payload, old_ts)
    assert N8NIntegrationGateway.verify_signature(secret, payload, old_sig, old_ts) is False
