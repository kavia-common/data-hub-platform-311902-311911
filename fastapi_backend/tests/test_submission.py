import pytest

from tests.conftest import assert_audit_log_created

# FR-PUB-001: Submission via web portal API creates a new "publishing request"/submission record.
# NFR-PUB-AUDIT-001: All user actions must be audit-logged with correlation_id and UTC timestamp.


@pytest.mark.fr_pub
def test_submit_data_product_success_creates_audit_log(client, headers, request_id):
    """
    FR-PUB: A user submits a data product for publishing.

    TDD/OpenAPI assumption:
      POST /publishing/submissions
      Request body includes identifying info for the product + version + artifacts.
      Response includes a submission_id.
    """
    payload = {
        "product_id": "dp_sales",
        "version": "1.0.0",
        "title": "Sales Dataset",
        "artifact_uris": ["s3://bucket/sales.csv"],
        "submitted_by": "alice@example.com",
    }

    resp = client.post("/publishing/submissions", json=payload, headers=headers)
    assert resp.status_code == 201

    data = resp.json()
    assert "submission_id" in data and isinstance(data["submission_id"], str) and data["submission_id"]

    # Audit log assertion
    assert_audit_log_created(
        client,
        expected_action="SUBMISSION_CREATE",
        expected_outcome="SUCCESS",
        correlation_id=request_id,
        expected_entity_id=data["submission_id"],
    )


@pytest.mark.fr_pub
def test_submit_data_product_invalid_payload_creates_failure_audit_log(client, headers, request_id):
    """
    FR-PUB + NFR-PUB-AUDIT: Even if submission fails validation, an AuditLog FAILURE entry must be created.
    """
    # Missing required fields like product_id and version
    payload = {"title": "Missing Required Fields"}

    resp = client.post("/publishing/submissions", json=payload, headers=headers)

    # OpenAPI-driven expectation: 422 for validation issues
    assert resp.status_code == 422

    assert_audit_log_created(
        client,
        expected_action="SUBMISSION_CREATE",
        expected_outcome="FAILURE",
        correlation_id=request_id,
    )
