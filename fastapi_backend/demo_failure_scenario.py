#!/usr/bin/env python3
"""
Demo script: Quality Gate enforcement (freshness rule) failure.

This script:
1) Calls the FastAPI backend on http://localhost:3001
2) Creates a submission (Publisher persona headers)
3) Requests validation with gate="freshness_check" to trigger the expected 422 gate failure
4) Prints status code + error payload (including code/message), and provides diagnostics if unreachable.

Note:
- The current backend implementation's freshness gate is exercised via the validate endpoint
  (POST /publishing/submissions/{submission_id}/validate with {"gate":"freshness_check"}).
- The submission-create OpenAPI schema does not currently accept a last_modified field.
  We still include a demo last_modified timestamp (48h ago) under a non-schema key and
  also attach it to an artifact URI query string so it remains visible for demo purposes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests


# PUBLIC_INTERFACE
def main() -> int:
    """Run the freshness-gate failure demo and return process exit code."""
    base_url = "http://localhost:3001"
    correlation_id = "demo_freshness_viol_0001"

    # "Authenticate as Publisher" - this minimal app doesn't enforce auth,
    # but we include a role header for demo clarity/future evolution.
    headers = {
        "X-Request-Id": correlation_id,
        "X-User-Role": "publisher",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    last_modified_utc = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")

    # The submission API schema is minimal (product_id, version, title, artifact_uris, submitted_by).
    # We keep payload strictly compatible so the request is accepted.
    submission_payload: Dict[str, Any] = {
        "product_id": "dp_demo_freshness_fail",
        "version": "0.0.1",
        "title": "Demo Dataset (Stale - 48h old)",
        # Attach last_modified as query string to keep it visible in the submission artifact reference
        # without violating the strict schema.
        "artifact_uris": [f"s3://bucket/demo.csv?last_modified={last_modified_utc}"],
        "submitted_by": "publisher@example.com",
        # Extra field (may be ignored/rejected by strict validators; current app ignores extra keys)
        "last_modified": last_modified_utc,
    }

    try:
        # 1) Create submission
        create_url = f"{base_url}/publishing/submissions"
        create_resp = requests.post(create_url, headers=headers, json=submission_payload, timeout=10)

        print("Create submission status:", create_resp.status_code)
        create_body = _safe_json(create_resp)
        print("Create submission body:", _pretty(create_body))

        if create_resp.status_code != 201:
            print("Submission creation did not succeed; cannot continue to validation step.")
            return 1

        submission_id = (create_body or {}).get("submission_id")
        if not submission_id:
            print("Missing submission_id in create response; cannot continue.")
            return 1

        # 2) Validate submission against freshness gate (expected 422)
        validate_url = f"{base_url}/publishing/submissions/{submission_id}/validate"
        validate_payload = {"gate": "freshness_check"}
        validate_resp = requests.post(validate_url, headers=headers, json=validate_payload, timeout=10)

        print("\nValidate (freshness_check) status:", validate_resp.status_code)
        validate_body = _safe_json(validate_resp)
        print("Validate (freshness_check) body:", _pretty(validate_body))

        # Helpful extraction for typical gate error payloads: { code, message, details }
        if isinstance(validate_body, dict):
            code = validate_body.get("code")
            msg = validate_body.get("message")
            if code or msg:
                print("\nParsed error:")
                print("  code:", code)
                print("  message:", msg)

        # Expected outcome: 422 with FRESHNESS_CHECK_FAILED (per tests)
        return 0

    except requests.exceptions.ConnectionError:
        print(f"ERROR: Unable to connect to {base_url}. Is the FastAPI app running on port 3001?")
        print("Tip: open /docs in your browser or run the backend service, then re-run this script.")
        return 2
    except requests.exceptions.Timeout:
        print(f"ERROR: Request to {base_url} timed out. Is the service responsive?")
        return 3
    except Exception as exc:  # noqa: BLE001 - demo script: print full diagnostics
        print("ERROR: Unexpected exception occurred.")
        print(repr(exc))
        return 4


def _safe_json(resp: requests.Response) -> Optional[Any]:
    """Best-effort JSON parsing; fall back to text."""
    try:
        if not resp.text:
            return None
        return resp.json()
    except Exception:
        return {"_non_json_body": resp.text}


def _pretty(obj: Any) -> str:
    """Pretty print JSON-like objects for terminal output."""
    try:
        return json.dumps(obj, indent=2, sort_keys=True)
    except Exception:
        return str(obj)


if __name__ == "__main__":
    raise SystemExit(main())
