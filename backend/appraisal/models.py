# backend/appraisal/models.py
from pydantic import BaseModel
from typing import Optional, Dict, Any


class AppraisalSaveRequest(BaseModel):
    """Employee saves (draft) or submits their appraisal form."""
    employeeId:   str
    period:       str                   # e.g. "2024-25"
    answers:      Dict[str, Any]        # { "C1": "text...", "C3": 4, ... }
    status:       str = "draft"         # "draft" | "submitted"


class AppraisalEligibilityResponse(BaseModel):
    eligible:     bool
    reason:       str
    doj:          Optional[str] = None
    one_year_date: Optional[str] = None
 
 
class AppraisalReviewRequest(BaseModel):
    action: str                               # "approve" | "reject"
    tl_responses: Optional[Dict[str, Any]] = None
    pnd_responses: Optional[Dict[str, Any]] = None
    remarks: Optional[str] = None
 
