"""clearancewatch — per-job subcontractor compliance: clearances, insurance, licences.

Not legal advice. Two rules are checked against the regulators' own pages (see
README): WSIB clearances are valid up to 90 days, and WCB Alberta wants a
clearance before hiring and before releasing payment. "Valid for the whole job"
and "an Alberta letter covers work only up to its date" are conservative house
policy, not quoted law.
"""

from .model import Clearance, DataError, Insurance, Job, Licence, Requirements, Subcontractor
from .audit import Finding, audit, renewals

__version__ = "0.2.0"
__author__ = "Calas Automations Inc."
__copyright__ = "Copyright (c) 2026 Calas Automations Inc."
__all__ = [
    "Job", "Subcontractor", "Clearance", "Insurance", "Licence", "Requirements", "DataError",
    "audit", "renewals", "Finding", "__version__", "__author__",
]
