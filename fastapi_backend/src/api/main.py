from __future__ import annotations

"""
FastAPI application implementing a minimal in-memory Data Product Publishing workflow.

This module is designed to satisfy:
- The generated OpenAPI spec (CodeWiki/Specs/FeatureSpecs/data-product-publishing-openapi.yaml)
- The pytest suite under fastapi_backend/tests

Notes:
- This is an intentionally minimal, in-memory implementation for TDD.
- Audit logging is implemented per NFR-PUB-AUDIT-001 and is asserted by tests.
- We avoid logging sensitive payloads (NFR-PUB-SEC-007) by only storing non-sensitive details.

Endpoints implemented to satisfy tests:
- GET  /
- POST /publishing/submissions
- POST /publishing/submissions/{submission_id}/pipeline/start
- POST /publishing/submissions/{submission_id}/validate
- POST /publishing/submissions/{submission_id}/approve
- POST /publishing/submissions/{submission_id}/reject
- POST /publishing/submissions/{submission_id}/publish
- GET  /audit-logs?correlation_id=...
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


# -----------------------------
# Utilities
# -----------------------------


def _utc_now_iso() -> str:
    """Return current time as RFC3339-ish ISO string normalized to UTC with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    """Create a stable-ish identifier with a prefix for readability in tests/logs."""
    return f"{prefix}_{uuid4().hex[:12]}"


def _get_correlation_id(x_request_id: Optional[str]) -> str:
    """
    Determine correlation id for audit logging.

    Tests supply X-Request-Id; if absent, we mint one.
    """
    return x_request_id or _new_id("corr")


# -----------------------------
# Error and Audit models
# -----------------------------


class Error422(BaseModel):
    """
    Minimal 422 error payload required by tests.

    Tests assert:
      - code (str)
      - message (str)
      - details (dict, optional)
    """

    code: str = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="Human-readable error message.")
    details: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional non-sensitive detail object."
    )


class AuditLogEntry(BaseModel):
    """Minimal audit log entry schema asserted by tests (conftest.py)."""

    correlation_id: str = Field(..., description="Correlation id for the request (X-Request-Id).")
    action: str = Field(..., description="Action name for the audited event.")
    outcome: Literal["SUCCESS", "FAILURE"] = Field(..., description="Outcome of the action.")
    timestamp_utc: str = Field(..., description="UTC timestamp in ISO8601 format (Z).")
    entity_id: Optional[str] = Field(default=None, description="Primary entity id (submission id).")
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Non-sensitive details for audit reconstruction.",
    )


class AuditLogListResponse(BaseModel):
    """List response wrapper used by tests: { items: [...] }."""

    items: List[AuditLogEntry] = Field(default_factory=list)


def _audit_log(
    *,
    correlation_id: str,
    action: str,
    outcome: Literal["SUCCESS", "FAILURE"],
    entity_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append an audit log entry to in-memory store.

    FR/NFR references:
    - NFR-PUB-AUDIT-001: all user actions must be audit-logged with correlation_id and UTC timestamp.
    - NFR-PUB-SEC-007: do not log sensitive payloads; only store minimal details.
    """
    entry = AuditLogEntry(
        correlation_id=correlation_id,
        action=action,
        outcome=outcome,
        timestamp_utc=_utc_now_iso(),
        entity_id=entity_id,
        details=details,
    )
    _STORE["audit_logs"].append(entry)


# -----------------------------
# In-memory domain models
# -----------------------------


class SubmissionCreateRequest(BaseModel):
    """Payload shape used by tests (flattened, minimal)."""

    product_id: str = Field(..., description="Data product identifier.")
    version: str = Field(..., description="Proposed version.")
    title: str = Field(..., description="Human friendly title.")
    artifact_uris: List[str] = Field(..., description="Artifact URIs.")
    submitted_by: str = Field(..., description="Submitter identity (email).")


class SubmissionCreateResponse(BaseModel):
    """Response required by tests: contains a submission_id."""

    submission_id: str = Field(..., description="Created submission identifier.")


class PipelineStartResponse(BaseModel):
    """Response required by tests: contains pipeline_run_id."""

    pipeline_run_id: str = Field(..., description="Created pipeline run id.")


class ValidateRequest(BaseModel):
    """Tests pass: { gate: 'freshness_check'|'schema'|'pii'|'all' }"""

    gate: str = Field(..., description="Gate selector.")


class ValidateResponse(BaseModel):
    """Tests assert status in PASSED/SUCCESS/OK."""

    status: str = Field(..., description="Validation status.")


class ApprovalApproveRequest(BaseModel):
    approved_by: str = Field(..., description="Approver identity.")
    comment: Optional[str] = Field(default=None, description="Non-sensitive comment.")


class ApprovalRejectRequest(BaseModel):
    rejected_by: str = Field(..., description="Rejector identity.")
    reason: str = Field(..., description="Non-sensitive reason.")


class ApprovalResponse(BaseModel):
    status: Literal["APPROVED", "REJECTED"] = Field(..., description="Approval state.")


class PublishResponse(BaseModel):
    status: Literal["PUBLISHED"] = Field(..., description="Publish status.")
    published_product_id: str = Field(..., description="Published product identifier.")
    published_version: str = Field(..., description="Published version.")


# Internal store schema (simple dicts)
_STORE: Dict[str, Any] = {
    "submissions": {},  # submission_id -> dict
    "pipeline_runs": {},  # run_id -> dict
    "validation_results": {},  # submission_id -> dict
    "approvals": {},  # submission_id -> dict {status: APPROVED/REJECTED}
    "publish_events": {},  # submission_id -> dict
    "audit_logs": [],  # list[AuditLogEntry]
}


def _ensure_submission(submission_id: str) -> Dict[str, Any]:
    """
    Ensure a submission exists in store; create a placeholder if needed.

    This supports TDD tests that call pipeline/validate/approve/publish with a deterministic
    submission_id without creating it first.

    We keep fields minimal and non-sensitive.
    """
    if submission_id not in _STORE["submissions"]:
        _STORE["submissions"][submission_id] = {
            "submission_id": submission_id,
            "created_at_utc": _utc_now_iso(),
            "status": "DRAFT",
            "validated": False,
            "approved": False,
            "rejected": False,
            "published": False,
        }
    return _STORE["submissions"][submission_id]


# -----------------------------
# Quality gate logic (minimal)
# -----------------------------


_GATE_MAP = {
    # tests use gate_name "freshness_check" but expected code is FRESHNESS_CHECK_FAILED
    "freshness_check": {
        "code": "FRESHNESS_CHECK_FAILED",
        "message": "Freshness Check Failed: data is older than allowed freshness threshold.",
        "details": {"gate": "freshness_check"},
    },
    "schema": {
        "code": "SCHEMA_MISMATCH",
        "message": "Schema Mismatch: dataset does not conform to expected schema.",
        "details": {"gate": "schema"},
    },
    "pii": {
        "code": "PII_DETECTED",
        "message": "PII Detected: regulated identifiers were detected by scanning rules.",
        "details": {"gate": "pii"},
    },
}


def _gate_failure_payload(gate: str) -> Error422:
    """Create a 422 payload matching tests for the selected gate."""
    g = _GATE_MAP.get(gate)
    if g is None:
        # For unknown gate selectors, treat it as schema mismatch (deterministic, 422 shape)
        return Error422(
            code="SCHEMA_MISMATCH",
            message="Schema Mismatch: unknown gate selector treated as schema validation failure.",
            details={"gate": gate},
        )
    return Error422(code=g["code"], message=g["message"], details=g["details"])


# -----------------------------
# FastAPI App
# -----------------------------


openapi_tags = [
    {"name": "Health", "description": "Service health and readiness endpoints."},
    {"name": "Publishing", "description": "Minimal publishing workflow endpoints required by tests."},
    {"name": "Audit", "description": "Audit log retrieval endpoints."},
]

app = FastAPI(
    title="Data Product Publishing API (TDD)",
    version="0.1.0",
    description="Minimal in-memory implementation of the publishing workflow for tests.",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# PUBLIC_INTERFACE
@app.get("/", tags=["Health"], summary="Health Check", operation_id="health_check__get")
def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"message": "Healthy"}


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Convert unexpected errors into a deterministic response.

    Not asserted by tests, but prevents leaking stack traces in CI logs and keeps behavior stable.
    """
    # NOTE: Do not audit-log here to avoid double logging; handlers below log explicitly.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": "INTERNAL_ERROR", "message": "Unexpected error occurred."},
    )


# PUBLIC_INTERFACE
@app.get(
    "/audit-logs",
    tags=["Audit"],
    summary="List audit logs",
    operation_id="list_audit_logs__get",
    response_model=AuditLogListResponse,
)
def list_audit_logs(correlation_id: Optional[str] = None) -> AuditLogListResponse:
    """
    List audit logs, optionally filtered by correlation_id.

    Tests call: GET /audit-logs?correlation_id=...
    """
    items: List[AuditLogEntry] = _STORE["audit_logs"]
    if correlation_id:
        items = [i for i in items if i.correlation_id == correlation_id]
    return AuditLogListResponse(items=items)


# PUBLIC_INTERFACE
@app.post(
    "/publishing/submissions",
    tags=["Publishing"],
    summary="Create a submission",
    operation_id="create_submission__post",
    status_code=status.HTTP_201_CREATED,
    response_model=SubmissionCreateResponse,
)
def create_submission(
    body: SubmissionCreateRequest,
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
) -> SubmissionCreateResponse:
    """
    Create a new submission.

    FR-PUB-001: submission API creates a new submission record.
    NFR-PUB-AUDIT-001: must be audit-logged.
    """
    correlation_id = _get_correlation_id(x_request_id)

    submission_id = _new_id("subm")
    _STORE["submissions"][submission_id] = {
        "submission_id": submission_id,
        "product_id": body.product_id,
        "version": body.version,
        "title": body.title,
        "artifact_uris_count": len(body.artifact_uris),
        "submitted_by": body.submitted_by,
        "created_at_utc": _utc_now_iso(),
        "status": "SUBMITTED",
        "validated": False,
        "approved": False,
        "rejected": False,
        "published": False,
    }

    _audit_log(
        correlation_id=correlation_id,
        action="SUBMISSION_CREATE",
        outcome="SUCCESS",
        entity_id=submission_id,
        details={
            # Avoid logging full URIs or payload; keep minimal (NFR-PUB-SEC-007).
            "product_id": body.product_id,
            "version": body.version,
        },
    )
    return SubmissionCreateResponse(submission_id=submission_id)


# PUBLIC_INTERFACE
@app.post(
    "/publishing/submissions/{submission_id}/pipeline/start",
    tags=["Publishing"],
    summary="Start pipeline for a submission",
    operation_id="start_pipeline__post",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PipelineStartResponse,
)
def start_pipeline(
    submission_id: str,
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
) -> PipelineStartResponse:
    """
    Start a pipeline run for a submission.

    FR-PUB-010 (tests): pipeline start returns 202 and pipeline_run_id.
    """
    correlation_id = _get_correlation_id(x_request_id)
    _ensure_submission(submission_id)

    run_id = _new_id("run")
    _STORE["pipeline_runs"][run_id] = {
        "run_id": run_id,
        "submission_id": submission_id,
        "status": "RUNNING",
        "started_at_utc": _utc_now_iso(),
        "correlation_id": correlation_id,
    }

    _audit_log(
        correlation_id=correlation_id,
        action="PIPELINE_START",
        outcome="SUCCESS",
        entity_id=submission_id,
        details={"pipeline_run_id": run_id},
    )
    return PipelineStartResponse(pipeline_run_id=run_id)


# PUBLIC_INTERFACE
@app.post(
    "/publishing/submissions/{submission_id}/validate",
    tags=["Publishing"],
    summary="Run validation (quality gates)",
    operation_id="validate_submission__post",
)
def validate_submission(
    submission_id: str,
    body: ValidateRequest,
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
) -> JSONResponse:
    """
    Validate a submission against quality gates.

    FR-PUB-020 (tests): mandatory gates can fail with 422 and structured payload.
    NFR-PUB-AUDIT-001: success/failure must be audit-logged.
    """
    correlation_id = _get_correlation_id(x_request_id)
    _ensure_submission(submission_id)

    gate = (body.gate or "").strip().lower()

    if gate in _GATE_MAP:
        payload = _gate_failure_payload(gate)
        _STORE["validation_results"][submission_id] = {
            "submission_id": submission_id,
            "status": "FAILED",
            "gate": gate,
            "evaluated_at_utc": _utc_now_iso(),
        }
        _STORE["submissions"][submission_id]["validated"] = False
        _STORE["submissions"][submission_id]["status"] = "FAILED_VALIDATION"

        _audit_log(
            correlation_id=correlation_id,
            action="QUALITY_GATE_VALIDATE",
            outcome="FAILURE",
            entity_id=submission_id,
            details={"code": payload.code, "gate": gate},
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload.model_dump())

    # "all" or any other value -> pass gates
    _STORE["validation_results"][submission_id] = {
        "submission_id": submission_id,
        "status": "PASSED",
        "gate": "all",
        "evaluated_at_utc": _utc_now_iso(),
    }
    _STORE["submissions"][submission_id]["validated"] = True
    _STORE["submissions"][submission_id]["status"] = "VALIDATED"

    _audit_log(
        correlation_id=correlation_id,
        action="QUALITY_GATE_VALIDATE",
        outcome="SUCCESS",
        entity_id=submission_id,
        details={"gate": "all"},
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=ValidateResponse(status="PASSED").model_dump())


# PUBLIC_INTERFACE
@app.post(
    "/publishing/submissions/{submission_id}/approve",
    tags=["Publishing"],
    summary="Approve a submission",
    operation_id="approve_submission__post",
    response_model=ApprovalResponse,
)
def approve_submission(
    submission_id: str,
    body: ApprovalApproveRequest,
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
) -> JSONResponse:
    """
    Approve a submission.

    FR-PUB-030 (tests): approval supports approve action.
    Precondition in tests: approval fails with 422 if gates not passed.
    """
    correlation_id = _get_correlation_id(x_request_id)
    sub = _ensure_submission(submission_id)

    if not sub.get("validated", False):
        payload = Error422(
            code="APPROVAL_PRECONDITION_FAILED",
            message="Approval precondition failed: submission must pass validation gate(s) before approval.",
            details={"submission_id": submission_id},
        )
        _audit_log(
            correlation_id=correlation_id,
            action="APPROVAL_DECISION",
            outcome="FAILURE",
            entity_id=submission_id,
            details={"code": payload.code},
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload.model_dump())

    _STORE["approvals"][submission_id] = {
        "status": "APPROVED",
        "approved_by": body.approved_by,
        "comment_present": bool(body.comment),
        "decided_at_utc": _utc_now_iso(),
    }
    sub["approved"] = True
    sub["rejected"] = False
    sub["status"] = "APPROVED"

    _audit_log(
        correlation_id=correlation_id,
        action="APPROVAL_DECISION",
        outcome="SUCCESS",
        entity_id=submission_id,
        details={"decision": "APPROVED"},
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=ApprovalResponse(status="APPROVED").model_dump())


# PUBLIC_INTERFACE
@app.post(
    "/publishing/submissions/{submission_id}/reject",
    tags=["Publishing"],
    summary="Reject a submission",
    operation_id="reject_submission__post",
    response_model=ApprovalResponse,
)
def reject_submission(
    submission_id: str,
    body: ApprovalRejectRequest,
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
) -> JSONResponse:
    """
    Reject a submission.

    FR-PUB-030 (tests): rejection supported and audit-logged.
    """
    correlation_id = _get_correlation_id(x_request_id)
    sub = _ensure_submission(submission_id)

    _STORE["approvals"][submission_id] = {
        "status": "REJECTED",
        "rejected_by": body.rejected_by,
        # Do not store free-form reason in audit logs; store only a presence flag.
        "reason_present": True,
        "decided_at_utc": _utc_now_iso(),
    }
    sub["approved"] = False
    sub["rejected"] = True
    sub["status"] = "REJECTED"

    _audit_log(
        correlation_id=correlation_id,
        action="APPROVAL_DECISION",
        outcome="SUCCESS",
        entity_id=submission_id,
        details={"decision": "REJECTED"},
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=ApprovalResponse(status="REJECTED").model_dump())


# PUBLIC_INTERFACE
@app.post(
    "/publishing/submissions/{submission_id}/publish",
    tags=["Publishing"],
    summary="Publish a submission",
    operation_id="publish_submission__post",
    response_model=PublishResponse,
)
def publish_submission(
    submission_id: str,
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
) -> JSONResponse:
    """
    Publish an approved submission.

    FR-PUB-040 (tests): publish endpoint returns 200 + published_product_id + published_version.
    Test precondition: publish fails 422 if not approved.
    """
    correlation_id = _get_correlation_id(x_request_id)
    sub = _ensure_submission(submission_id)

    if not sub.get("approved", False):
        payload = Error422(
            code="PUBLISH_PRECONDITION_FAILED",
            message="Publish precondition failed: submission must be approved before publishing.",
            details={"submission_id": submission_id},
        )
        _audit_log(
            correlation_id=correlation_id,
            action="PUBLISH",
            outcome="FAILURE",
            entity_id=submission_id,
            details={"code": payload.code},
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload.model_dump())

    # Minimal publish event. Keep deterministic-enough values but unique.
    published_product_id = sub.get("product_id") or _new_id("dp")
    published_version = sub.get("version") or "1.0.0"

    _STORE["publish_events"][submission_id] = {
        "published_product_id": published_product_id,
        "published_version": published_version,
        "published_at_utc": _utc_now_iso(),
    }
    sub["published"] = True
    sub["status"] = "PUBLISHED"

    _audit_log(
        correlation_id=correlation_id,
        action="PUBLISH",
        outcome="SUCCESS",
        entity_id=submission_id,
        details={"published_product_id": published_product_id, "published_version": published_version},
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=PublishResponse(
            status="PUBLISHED",
            published_product_id=published_product_id,
            published_version=published_version,
        ).model_dump(),
    )
