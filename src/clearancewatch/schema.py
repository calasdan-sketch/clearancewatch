"""The starter file and a JSON Schema for the jobs file.

``tests/test_round3.py`` keeps the schema's field names in step with the model,
so the two cannot drift apart silently.
"""
from __future__ import annotations

from typing import Any, Dict

TEMPLATE = """[
  {
    "name": "Kitchen reno",
    "province": "ON",
    "start": "2026-02-01",
    "end": "2026-03-30",
    "requirements": { "min_liability": "C$2M" },
    "subs": [
      {
        "name": "Bob's Drywall",
        "trade": "drywall",
        "clearance": { "issuer": "WSIB", "number": "1234567", "issued": "2026-01-10", "expires": "2026-04-10" },
        "insurance": { "provider": "Aviva", "policy": "GL-9", "coverage": "C$2M", "expires": "2026-12-31" },
        "licences": [ { "name": "Fall protection", "expires": "2026-09-01" } ]
      }
    ]
  }
]"""

_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$", "description": "YYYY-MM-DD"}
_TEXT = {"type": ["string", "number", "null"]}
_BOOL = {"type": ["boolean", "null"]}


def _obj(props: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": "object", "properties": props}
    out.update(extra)
    return out


def jobs_schema() -> Dict[str, Any]:
    clearance = _obj({"issuer": _TEXT, "number": _TEXT, "issued": _DATE, "expires": _DATE, "covered_until": _DATE,
                       "status": _TEXT})
    insurance = _obj({"provider": _TEXT, "policy": _TEXT, "coverage": {"type": ["string", "number", "null"]},
                      "expires": _DATE, "additional_insured": _BOOL, "waiver_of_subrogation": _BOOL,
                      "primary_noncontributory": _BOOL})
    licence = _obj({"name": _TEXT, "number": _TEXT, "authority": _TEXT, "expires": _DATE})
    sub = _obj({"name": _TEXT, "province": _TEXT, "trade": _TEXT, "clearance": clearance,
                "clearances": {"type": "array", "items": clearance}, "insurance": insurance,
                "licences": {"type": "array", "items": licence}, "clearance_exempt": _TEXT,
                "start": _DATE, "supply_only": _BOOL},
               )
    requirements = _obj({"min_liability": {"type": ["string", "number"]}, "additional_insured": _BOOL,
                         "waiver_of_subrogation": _BOOL, "primary_noncontributory": _BOOL,
                         "required_licences": {"type": "object", "additionalProperties": {"type": "string"}}})
    job = _obj({"name": _TEXT, "province": _TEXT, "start": _DATE, "end": _DATE,
                "subs": {"type": "array", "items": sub}, "subcontractors": {"type": "array", "items": sub},
                "requirements": requirements, "payment_dates": {"type": "array", "items": _DATE}})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "clearancewatch jobs file",
        "description": "Unknown keys are allowed by this schema but clearancewatch reports them as unknown_field.",
        "anyOf": [{"type": "array", "items": job, "minItems": 1},
                  _obj({"jobs": {"type": "array", "items": job, "minItems": 1}}, required=["jobs"]),
                  job],
    }
