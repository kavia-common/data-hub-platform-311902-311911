import pytest

from tests.conftest import assert_audit_log_created, assert_error_payload_422

# FR-PUB-040: Publish approved data product.
# NFR-PUB-AUDIT-001: Publish attempts and outcomes must be audit-logged with correlation_id and UTC timestamp.


@pytest.fixture()
def submission_id() -> str:
    return "subm_test_publish_0001"


@pytest.mark.fr_pub
def test_publish_success_creates_audit_log(client, headers, request_id, submission_id):
    """
    TDD/OpenAPI assumption:
      POST /publishing/submissions/{submission_id}/publish
      returns 200 with { status: "PUBLISHED", published_product_id: "...", published_version: "..." }.
    """
    resp = client.post(f"/publishing/submissions/{submission_id}/publish", headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data.get("status") == "PUBLISHED"
    assert "published_product_id" in data and isinstance(data["published_product_id"], str) and data["published_product_id"]
    assert "published_version" in data and isinstance(data["published_version"], str) and data["published_version"]

    assert_audit_log_created(
        client,
        expected_action="PUBLISH",
        expected_outcome="SUCCESS",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )


@pytest.mark.fr_pub
def test_publish_fails_without_approval_creates_failure_audit_log(client, headers, request_id):
    """
    Publishing must fail (422) if submission is not approved; still must be audit-logged as FAILURE.
    """
    submission_id = "subm_test_unapproved_0001"
    resp = client.post(f"/publishing/submissions/{submission_id}/publish", headers=headers)

    assert resp.status_code == 422
    payload = resp.json()
    assert_error_payload_422(payload, expected_code="PUBLISH_PRECONDITION_FAILED", expected_message_pattern=r"approve|approval|precondition")

    assert_audit_log_created(
        client,
        expected_action="PUBLISH",
        expected_outcome="FAILURE",
        correlation_id=request_id,
        expected_entity_id=submission_id,
    )
