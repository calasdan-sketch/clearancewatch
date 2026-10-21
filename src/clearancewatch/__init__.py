"""clearancewatch — per-job subcontractor compliance: clearances, insurance, licences.

Not legal advice. Rules modelled from official sources (see README), verified
October 2026: WSIB clearances are valid up to 90 days and a principal must hold
a valid clearance for the whole job; WCB Alberta clearance letters cover work up
to the date of the letter.
"""

from .model import Clearance, Insurance, Job, Licence, Subcontractor
from .audit import Finding, audit, renewals

__version__ = "0.1.0"
__all__ = [
    "Job", "Subcontractor", "Clearance", "Insurance", "Licence",
    "audit", "renewals", "Finding", "__version__",
]
