import pytest

from tests.conftest import assert_audit_log_created, assert_error_payload_422

# FR-PUB-010: Pipeline start/processing can be initiated for a submission.
# FR-PUB-020: Quality gates run and can fail with 422 (unprocessable) for gate failures.
# NFR-PUB-AUDIT-001: All pipeline/gate outcomes must be audit-logged (SUCCESS/FAILURE).


@pytest.fixture()
def submission_id() -> str:
    # Deterministic seed id for TDD. Implementation can accept this or return its own IDs.
    return "subm_test_0001"


@pytest.mark.fr_pub
def test_pipeline_start_success_creates_audit_log(client, headers, request_id, submission_id):
    """
    TDD/OpenAPI assumption:
      POST /publishing/submissions/{submission_id}/pipeline/start
      returns 202 with a pipeline_run_id.
    """
    resp = client.post(f"/publishing/submissions/{submission_id}/pipeline/start", headers=headers)
    assert resp.status_code == 202

    data = resp.json()
    assert "pipeline_run_id" in data and isinstance(data["pipeline_run_id"], str) and data["pipeline_run_id"]

    assert_audit_log_created(
        client,
        expected_action="PIPELINE_START",
        expected_outcome="SUCCESS",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )


@pytest.mark.fr_pub
@pytest.mark.parametrize(
    "gate_name, expected_code, expected_message_pattern",
    [
        ("freshness_check", "FRESHNESS_CHECK_FAILED", r"Freshness Check Failed|freshness"),
        ("schema", "SCHEMA_MISMATCH", r"Schema Mismatch|schema"),
        ("pii", "PII_DETECTED", r"PII Detected|pii"),
    ],
    ids=["freshness_check_failed", "schema_mismatch", "pii_detected"],
)
def test_quality_gate_failure_422_creates_failure_audit_log(
    client,
    headers,
    request_id,
    submission_id,
    gate_name,
    expected_code,
    expected_message_pattern,
):
    """
    Explicit negative gate tests causing 422, with error payload aligned to the OpenAPI schema.

    TDD/OpenAPI assumption:
      POST /publishing/submissions/{submission_id}/validate
      Request body can select gate or supply context.
      On gate failure, returns 422 with structured error:
        { "code": "...", "message": "...", "details": {...} }
    """
    body = {"gate": gate_name}

    resp = client.post(f"/publishing/submissions/{submission_id}/validate", json=body, headers=headers)
    assert resp.status_code == 422

    payload = resp.json()
    assert_error_payload_422(payload, expected_code=expected_code, expected_message_pattern=expected_message_pattern)

    assert_audit_log_created(
        client,
        expected_action="QUALITY_GATE_VALIDATE",
        expected_outcome="FAILURE",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )


@pytest.mark.fr_pub
def test_quality_gate_success_creates_success_audit_log(client, headers, request_id, submission_id):
    """
    TDD/OpenAPI assumption:
      POST /publishing/submissions/{submission_id}/validate
      Returns 200 when all gates pass, including a summary.
    """
    body = {"gate": "all"}  # trigger full validation

    resp = client.post(f"/publishing/submissions/{submission_id}/validate", json=body, headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, dict)
    assert data.get("status") in {"PASSED", "SUCCESS", "OK"}

    assert_audit_log_created(
        client,
        expected_action="QUALITY_GATE_VALIDATE",
        expected_outcome="SUCCESS",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )
