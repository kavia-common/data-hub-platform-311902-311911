# data-hub-platform-311902-311911

## Validation Summary Report (GxP-Style)

### Purpose and scope

This repository contains a minimal, in-memory FastAPI implementation of a “Data Product Publishing” workflow that is sufficient to demonstrate and test a subset of the target GxP requirements and negative-testing behaviors. This section summarizes what was implemented versus the requirements baseline, and provides traceability to the executed automated tests and the target OpenAPI specification.

This summary is intended to be read as a lightweight validation report for the current code state. It is not a full Part 11 validated system; it is a TDD-oriented scaffold with audit-friendly behaviors verified by automated tests.

### Requirements baselines and controlled references

The following documents are treated as the requirements and design baselines for traceability:

- Functional Requirements (FR): `kavia-docs/data-product-publishing-functional-requirements.md`
- Non-Functional Requirements (NFR): `kavia-docs/data-product-publishing-non-functional-requirements.md`
- Target OpenAPI (intended surface): `kavia-docs/data-product-publishing-openapi.yaml`
- Test Plan (target / design-intent): `kavia-docs/primary-focus-workflow-test-plan.md`
- Requirements Traceability Matrix (RTM, target / design-intent): `kavia-docs/requirements-traceability-matrix.md`

Implementation entrypoint and executable behavior:

- FastAPI app: `data-hub-platform-311902-311911/fastapi_backend/src/api/main.py`
- Demo portal (static HTML): `data-hub-platform-311902-311911/fastapi_backend/index.html`
- Automated tests (pytest): `data-hub-platform-311902-311911/fastapi_backend/tests/`

### Build and test evidence (current state)

Automated tests exist and are designed to be deterministic. The FastAPI implementation is explicitly written to satisfy the test suite under `fastapi_backend/tests`.

The core evidence artifact for this summary is the automated test suite itself, which validates:

- Endpoint behavior (status codes and response body shapes).
- Deterministic negative testing behavior for gate failures and precondition failures.
- Minimal audit logging shape and UTC timestamping for audited actions.

### Implemented API surface (as-built)

The implemented endpoints (current code) are:

- `GET /` (health)
- `POST /publishing/submissions` (submission create)
- `POST /publishing/submissions/{submission_id}/pipeline/start` (pipeline start)
- `POST /publishing/submissions/{submission_id}/validate` (quality gate validation)
- `POST /publishing/submissions/{submission_id}/approve` (approval)
- `POST /publishing/submissions/{submission_id}/reject` (rejection)
- `POST /publishing/submissions/{submission_id}/publish` (publish)
- `GET /audit-logs?correlation_id=...` (audit log retrieval)

Notes:

- The target OpenAPI in `kavia-docs/data-product-publishing-openapi.yaml` describes a broader intended surface (for example `/submissions`, `/publish`, approval request objects, evidence packages). The current implementation uses the `/publishing/...` path prefix and implements only the minimal subset required for the current tests.

### Validation approach (how compliance-oriented behaviors are demonstrated)

The validation strategy used in this repository is “test-as-evidence” for the implemented subset:

- Each workflow action is expected to create an audit log entry with `correlation_id` (from `X-Request-Id`), `action`, `outcome`, and a UTC timestamp (`timestamp_utc`).
- Failures (including payload validation failures, gate failures, and workflow precondition failures) are expected to be deterministic and to produce structured error payloads for 422 responses in the domain endpoints that are explicitly modeled for gate/precondition failures.
- Client-side validation is intentionally avoided in the demo portal (`index.html`) to align with the stated GxP constraint that the backend is authoritative for validation.

### Traceability summary (FR/NFR → implementation → tests → outcome)

The table below is an “as-built” traceability view for what is currently implemented and verified. Items not present in this table should be treated as not implemented (or only specified as target state in the CodeWiki docs).

| Requirement ID | Requirement (summary) | As-built implementation evidence | Test evidence | Outcome |
|---|---|---|---|---|
| FR-PUB-001 | Submission and draft management (submission via API) | `POST /publishing/submissions` in `fastapi_backend/src/api/main.py` creates an in-memory submission and logs the event | `fastapi_backend/tests/test_submission.py::test_submit_data_product_success_creates_audit_log` | Pass |
| FR-PUB-002 (partial) | Mandatory validation gates (schema/freshness/completeness) | Implemented a minimal gate selector with deterministic failures for `freshness_check`, `schema`, `pii` via `POST /publishing/submissions/{id}/validate` | `fastapi_backend/tests/test_quality_gates.py::test_quality_gate_failure_422_creates_failure_audit_log` (parametrized) and `...::test_quality_gate_success_creates_success_audit_log` | Pass (subset) |
| FR-PUB-003 (partial) | Gate failure handling and blocking behavior | On gate failure, response is 422 with `{code,message,details}` and the submission status is set to `FAILED_VALIDATION` in-memory | Same as above quality gate tests; also validated by the demo failure scenario described below | Pass (subset) |
| FR-PUB-004 (not implemented) | Validation report generation, persistence, hashing | No persistent validation reports, hashes, or retrieval endpoints are implemented | Not covered by tests | Not implemented |
| FR-PUB-006 (not implemented) | Segregation of duties enforcement | No SoD logic is implemented; approvals only check “validated” precondition | Not covered by tests | Not implemented |
| FR-PUB-008 (not implemented) | E-signature / re-authentication for approval | Not implemented; approval request payload only includes `approved_by` and optional comment | Not covered by tests | Not implemented |
| FR-PUB-009 (partial) | Publishing, versioning, evidence package | `POST /publishing/submissions/{id}/publish` requires “approved” and returns published identifiers, but does not generate evidence packages or permanent IDs | `fastapi_backend/tests/test_publish.py::test_publish_success_creates_audit_log` and `...::test_publish_fails_without_approval_creates_failure_audit_log` | Pass (subset) |
| FR-PUB-012 (partial) | Audit trail for significant actions | Minimal audit logging exists for submit, validate, approve, reject, publish, pipeline start; includes correlation_id, action, outcome, UTC timestamp | Audit assertions are centralized in `fastapi_backend/tests/conftest.py::assert_audit_log_created` and exercised by all workflow tests | Pass (subset) |
| FR-PUB-015 (partial) | Requirements traceability enablement | RTM and test plan exist as documents; code includes comments referencing FR/NFR intent, but there is no enforced RTM gating in CI in this repo | Documents: `kavia-docs/requirements-traceability-matrix.md`, `kavia-docs/primary-focus-workflow-test-plan.md` | Documented (process), not enforced |
| NFR-PUB-ERR-002 (partial) | Structured and actionable errors | Domain endpoints return structured 422 payloads for gate and precondition failures; request body validation errors for submission creation use FastAPI’s default 422 payload | Domain 422: `test_quality_gates.py`, `test_approvals.py`, `test_publish.py`; request validation 422: `test_submission.py::test_submit_data_product_invalid_payload_creates_failure_audit_log` | Pass (current contract) |
| NFR-PUB-ERR-006 | UTC timestamps for audit records | Audit log timestamps are asserted as UTC-normalized and timezone-aware | `fastapi_backend/tests/conftest.py::_assert_audit_log_shape` | Pass |
| NFR-PUB-AUD-* (partial) | Audit readiness (coverage, legibility, retrievability) | Audit log entries are queryable via `GET /audit-logs` and contain minimal fields asserted by tests. Full ALCOA+ durability/immutability and retention are not implemented. | All tests use `GET /audit-logs?correlation_id=...` to confirm audit entries were created | Pass (minimal in-memory subset) |
| NFR-PUB-SEC-007 (partial) | Avoid sensitive data leakage in logs | Audit logs intentionally store only minimal non-sensitive details (for example product_id, version, gate code) | Indirect: implementation behavior in `main.py` and tests assert shape only (not content redaction) | Implemented (not formally tested for redaction) |

### OpenAPI alignment summary

The repository includes a target OpenAPI specification at `kavia-docs/data-product-publishing-openapi.yaml`. That specification is explicitly described as a “target” surface in the document itself.

As-built API behavior aligns conceptually with these OpenAPI themes:

- A health endpoint exists (`GET /`), matching the general “Health” concept (path differs in target spec vs implementation naming and operationId).
- A submission creation endpoint exists (implemented as `POST /publishing/submissions` rather than `POST /submissions`).
- A validation trigger exists (implemented as `POST /publishing/submissions/{id}/validate` rather than `POST /submissions/{id}/validate`).
- Negative testing patterns exist for “gate failures” returning 422, and are explicitly exercised in tests.

However, the following OpenAPI-described capabilities are not implemented in code:

- Evidence package retrieval endpoints (for example `/evidence/packages/{evidencePackageId}`).
- Governance/policy adapter behavior and fail-closed semantics on publish (`/publish` gate failures described in the target OpenAPI).
- Approval request objects and e-signature semantics as described in the target OpenAPI.
- Validation result retrieval by validationReportId (`/validation-results/{validationReportId}`).
- Pipeline run retrieval (`/pipeline-runs/{runId}`).

Accordingly, the target OpenAPI should currently be treated as a specification baseline, not an as-built contract.

### Manual/demo evidence (informational)

A demo HTML portal exists at `fastapi_backend/index.html`. It posts to:

- `http://localhost:8000/publishing/submissions`

The demo’s stated constraint is that it performs no client-side validation; it always submits to the backend and displays the backend response as the “System Audit Log” panel.

A reproducible negative test scenario is also captured in the user-provided curl output (see the attached user instructions file referenced by the orchestrator) demonstrating a gate failure response shape from:

- `POST /publishing/submissions/{submission_id}/validate` with a freshness gate selector, returning a 422 with `code=FRESHNESS_CHECK_FAILED`.

### Deviations, limitations, and open items (what is not validated/implemented)

The following requirements are explicitly not implemented in the current in-memory FastAPI implementation and therefore are not validated by automated tests:

- Evidence package generation, hashing/sealing, retention, immutability controls (FR-PUB-004, FR-PUB-009, FR-PUB-013, FR-PUB-014; many NFR-PUB-AUD controls).
- Identity provider integration, authentication/authorization, deny-by-default enforcement (NFR-PUB-SEC-001/003/004/009).
- Segregation of duties enforcement for approvals (FR-PUB-006 / NFR-PUB-SEC-005).
- E-signature / re-authentication semantics for approvals (FR-PUB-008 / NFR-PUB-AUD-009).
- Controlled deviation workflow (FR-PUB-010).
- Post-publication monitoring endpoints and behaviors (FR-PUB-011).
- Full alignment to the target OpenAPI path structure and operationIds.

### How to locate evidence quickly

- Implementation: `data-hub-platform-311902-311911/fastapi_backend/src/api/main.py`
- Tests (evidence-by-execution): `data-hub-platform-311902-311911/fastapi_backend/tests/`
  - Submission: `test_submission.py`
  - Pipeline + gates: `test_quality_gates.py`
  - Approvals: `test_approvals.py`
  - Publish: `test_publish.py`
  - Audit assertions: `conftest.py` (shape and UTC checks)
- Requirements baseline: `kavia-docs/data-product-publishing-functional-requirements.md` and `kavia-docs/data-product-publishing-non-functional-requirements.md`
- Target API spec: `kavia-docs/data-product-publishing-openapi.yaml`

### Conclusion

The current codebase implements and verifies (via automated tests) a minimal submission → validation (with deterministic gate failures) → approval/reject → publish workflow with correlation-id-based audit logging and UTC timestamping. The implementation is intentionally limited and does not yet satisfy the full FR/NFR baseline or the full target OpenAPI surface. This section provides the “as-built” traceability needed to understand what is currently validated and what remains as target-state requirements.
