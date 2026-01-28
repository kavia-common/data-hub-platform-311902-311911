import pytest

from tests.conftest import assert_audit_log_created, assert_error_payload_422

# FR-PUB-030: Approval workflow supports approve and reject actions.
# NFR-PUB-AUDIT-001: Approval decisions must be audit-logged.


@pytest.fixture()
def submission_id() -> str:
    return "subm_test_approve_0001"


@pytest.mark.fr_pub
def test_approve_submission_success_creates_audit_log(client, headers, request_id, submission_id):
    """
    TDD/OpenAPI assumption:
      POST /publishing/submissions/{submission_id}/approve
      returns 200 with { status: "APPROVED" }.
    """
    body = {"approved_by": "reviewer@example.com", "comment": "Looks good."}

    resp = client.post(f"/publishing/submissions/{submission_id}/approve", json=body, headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data.get("status") == "APPROVED"

    assert_audit_log_created(
        client,
        expected_action="APPROVAL_DECISION",
        expected_outcome="SUCCESS",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )


@pytest.mark.fr_pub
def test_reject_submission_success_creates_audit_log(client, headers, request_id, submission_id):
    """
    TDD/OpenAPI assumption:
      POST /publishing/submissions/{submission_id}/reject
      returns 200 with { status: "REJECTED" }.
    """
    body = {"rejected_by": "reviewer@example.com", "reason": "Insufficient metadata."}

    resp = client.post(f"/publishing/submissions/{submission_id}/reject", json=body, headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data.get("status") == "REJECTED"

    assert_audit_log_created(
        client,
        expected_action="APPROVAL_DECISION",
        expected_outcome="SUCCESS",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )


@pytest.mark.fr_pub
def test_approve_submission_fails_when_gates_not_passed_creates_failure_audit_log(client, headers, request_id):
    """
    Approval should fail (422) when prerequisites are not met (e.g., gates not passed),
    and MUST create an AuditLog FAILURE entry.

    TDD/OpenAPI assumption: 422 error payload with a specific code.
    """
    submission_id = "subm_test_not_validated_0001"
    body = {"approved_by": "reviewer@example.com", "comment": "Approving prematurely"}

    resp = client.post(f"/publishing/submissions/{submission_id}/approve", json=body, headers=headers)
    assert resp.status_code == 422

    payload = resp.json()
    assert_error_payload_422(payload, expected_code="APPROVAL_PRECONDITION_FAILED", expected_message_pattern=r"gate|validate|precondition")

    assert_audit_log_created(
        client,
        expected_action="APPROVAL_DECISION",
        expected_outcome="FAILURE",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )
