import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def app():
    """
    Provide the FastAPI app for testing.

    NOTE: TDD expectation: application will evolve to include publishing workflow routes.
    """
    # Importing from current app entrypoint. If later refactored, update this fixture.
    from src.api.main import app as fastapi_app  # noqa: WPS433 (runtime import is fine in tests)

    return fastapi_app


@pytest.fixture()
def client(app):
    """
    Provide a synchronous TestClient.

    We intentionally use TestClient to keep tests simple and aligned with typical FastAPI TDD.
    """
    return TestClient(app)


@pytest.fixture()
def request_id() -> str:
    """Deterministic request id used to correlate AuditLog entries to calls."""
    return "req_test_0001"


@pytest.fixture()
def headers(request_id: str) -> Dict[str, str]:
    """
    Default headers for workflow calls.

    TDD assumption: backend uses X-Request-Id (or similar) to correlate request->AuditLog.
    """
    return {"X-Request-Id": request_id}


def _parse_utc_timestamp(value: str) -> datetime:
    """
    Parse an RFC3339-ish timestamp and enforce UTC.

    Accepts ISO strings with 'Z' suffix or timezone offsets.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise AssertionError("AuditLog.timestamp must be timezone-aware (UTC).")
    return dt.astimezone(timezone.utc)


def _assert_audit_log_shape(log: Dict[str, Any]) -> None:
    """
    Assert minimal OpenAPI-like AuditLog schema shape.

    We keep this intentionally strict to drive implementation.
    """
    assert isinstance(log, dict), "Audit log entry must be a JSON object"

    # Correlation and identity
    assert "correlation_id" in log, "AuditLog must include correlation_id"
    assert isinstance(log["correlation_id"], str) and log["correlation_id"]

    assert "action" in log, "AuditLog must include action"
    assert isinstance(log["action"], str) and log["action"]

    assert "outcome" in log, "AuditLog must include outcome"
    assert log["outcome"] in {"SUCCESS", "FAILURE"}

    # Time
    assert "timestamp_utc" in log, "AuditLog must include timestamp_utc"
    ts = _parse_utc_timestamp(log["timestamp_utc"])
    # Ensure stored timestamp is UTC-normalized
    assert ts.tzinfo is not None
    assert ts.utcoffset() == timezone.utc.utcoffset(ts)

    # Optional but expected fields
    if "details" in log and log["details"] is not None:
        assert isinstance(log["details"], dict), "AuditLog.details must be an object when present"


def assert_audit_log_created(
    client: TestClient,
    *,
    expected_action: str,
    expected_outcome: str,
    correlation_id: str,
    expected_entity_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Assert an AuditLog entry exists for the given correlation_id + action + outcome.

    TDD assumption aligned to OpenAPI: an endpoint exists to query audit logs, e.g.
    GET /audit-logs?correlation_id=... returning { "items": [AuditLog...] }.

    Returns the matched AuditLog entry for further assertions.
    """
    assert expected_outcome in {"SUCCESS", "FAILURE"}

    resp = client.get("/audit-logs", params={"correlation_id": correlation_id})
    assert resp.status_code == 200, "Audit log query endpoint must exist and return 200"

    payload = resp.json()
    assert isinstance(payload, dict)
    assert "items" in payload, "Audit log list response must include items"
    assert isinstance(payload["items"], list)

    # Find matching entry
    matches = []
    for item in payload["items"]:
        _assert_audit_log_shape(item)
        if (
            item.get("correlation_id") == correlation_id
            and item.get("action") == expected_action
            and item.get("outcome") == expected_outcome
        ):
            matches.append(item)

    assert matches, (
        "Expected AuditLog not found. "
        f"correlation_id={correlation_id}, action={expected_action}, outcome={expected_outcome}"
    )

    # If entity id is part of schema, enforce it when expected.
    matched = matches[-1]
    if expected_entity_id is not None:
        assert matched.get("entity_id") == expected_entity_id

    return matched


def assert_error_payload_422(payload: Dict[str, Any], *, expected_code: str, expected_message_pattern: str) -> None:
    """
    Assert a 422 error payload consistent with a typical OpenAPI validation/gate failure schema.

    TDD expectation (OpenAPI-aligned): payload includes:
      - code: machine-readable error code (e.g., FRESHNESS_CHECK_FAILED)
      - message: human-readable message
      - details: object (optional)
    """
    assert isinstance(payload, dict)
    assert payload.get("code") == expected_code
    assert "message" in payload and isinstance(payload["message"], str)
    assert re.search(expected_message_pattern, payload["message"]), (
        f"message did not match pattern. pattern={expected_message_pattern}, message={payload['message']}"
    )
    if "details" in payload:
        assert isinstance(payload["details"], dict)
