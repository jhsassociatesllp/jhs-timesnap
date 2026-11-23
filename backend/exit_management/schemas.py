# backend/exit_management/schemas.py
"""Pydantic models for the Employee Exit Management module.

Every field is optional here so the same models accept a half-filled DRAFT;
`service.missing_for_submit` then checks the required ones for a final submit.
The signed-in employee's own details (name, code, designation, ...) are never
read from the request - the server fills them in from the employee database.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Rating = Literal["Good", "Satisfactory", "Poor"]
YesNo = Literal["Yes", "No"]
Text = Optional[str]

MAX_TEXT = 5000


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ManagerFeedback(_Base):
    team_management: Optional[Rating] = None
    communication: Optional[Rating] = None
    motivation: Optional[Rating] = None
    technical_skills: Optional[Rating] = None
    fairness: Optional[Rating] = None
    approachability: Optional[Rating] = None
    relationship_with_other_teams: Optional[Rating] = None
    management_skills: Optional[Rating] = None


class CompanyFeedback(_Base):
    company_culture: Optional[Rating] = None
    learning_experience: Optional[Rating] = None
    rewards_recognition: Optional[Rating] = None
    performance_review_system: Optional[Rating] = None
    physical_working_conditions: Optional[Rating] = None
    facilities: Optional[Rating] = None
    opportunity_for_growth: Optional[Rating] = None
    management_skills: Optional[Rating] = None


class ExitInterview(_Base):
    would_rejoin: Optional[YesNo] = None                                   # Q17
    systems_and_processes: Optional[str] = Field(None, max_length=MAX_TEXT)  # Q18
    team_experience: Optional[str] = Field(None, max_length=MAX_TEXT)        # Q19
    resignation_reason: Optional[str] = Field(None, max_length=MAX_TEXT)     # Q20
    better_prospect: Optional[YesNo] = None                                # Q21
    new_employer: Optional[str] = Field(None, max_length=300)                # Q21 (if Yes)
    pull_factors: Optional[str] = Field(None, max_length=MAX_TEXT)           # Q22
    recommend_reason: Optional[str] = Field(None, max_length=MAX_TEXT)       # Q23 (if No): why the company is not recommended
    recommend_company: Optional[YesNo] = None                              # Q23
    jhs_memories: Optional[str] = Field(None, max_length=MAX_TEXT)           # Q24
    improvements: Optional[str] = Field(None, max_length=MAX_TEXT)           # Q25
    employee_benefits: Optional[str] = Field(None, max_length=MAX_TEXT)      # Q26
    departure_prevention: Optional[str] = Field(None, max_length=MAX_TEXT)   # Q27


class ExitFormPayload(_Base):
    """What the browser may send. Dates are ISO `YYYY-MM-DD` strings."""
    resignation_date: Optional[str] = Field(None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    last_working_date: Optional[str] = Field(None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    manager_feedback: ManagerFeedback = Field(default_factory=ManagerFeedback)
    company_feedback: CompanyFeedback = Field(default_factory=CompanyFeedback)
    exit_interview: ExitInterview = Field(default_factory=ExitInterview)
    # The signature is NOT part of this payload: it is a file uploaded through /upload-signature (GridFS)


# ── Reporting Manager: reject + Project Related Details (handover) form ──────────
class RejectPayload(_Base):
    reason: str = Field(..., min_length=5, max_length=1000)     # shown to the employee on their tracker


class HandoverRowIn(_Base):
    key: str = Field(..., max_length=40)
    option: Optional[YesNo] = None
    remarks: Optional[str] = Field(None, max_length=1000)


class HandoverPayload(_Base):
    """Yes/No and remarks of the four rows. Signatures are NOT here: each row's file is uploaded on its own."""
    items: list[HandoverRowIn] = Field(default_factory=list, max_length=4)


YesNoNA = Literal["Yes", "No", "NA"]


class ItRowIn(_Base):
    key: str = Field(..., max_length=40)
    option: Optional[YesNoNA] = None
    remarks: Optional[str] = Field(None, max_length=1000)


class ItPayload(_Base):
    """Yes / No / NA and remarks of the IT Clearance rows. Signatures are NOT here: each row's file is uploaded on its own."""
    items: list[ItRowIn] = Field(default_factory=list, max_length=12)


class HrPayload(_Base):
    """HR Clearance: Yes / No + remarks of the three rows, and the HR comments. Signatures are uploaded on their own."""
    items: list[HandoverRowIn] = Field(default_factory=list, max_length=3)
    hr_comments: Optional[str] = Field(None, max_length=2000)
