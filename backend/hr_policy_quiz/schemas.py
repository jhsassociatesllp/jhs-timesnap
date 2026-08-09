from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class CandidateLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AddCandidatesRequest(BaseModel):
    # Comma separated in the UI, parsed into a list before hitting the API.
    emails: List[EmailStr]
    document_id: str


class RegeneratePasswordRequest(BaseModel):
    emails: List[EmailStr]


class AnswerItem(BaseModel):
    question_id: str
    selected_option: Optional[int] = None  # index 0-3, null if not attempted in time
    time_taken_seconds: float = 0


class SubmitQuizRequest(BaseModel):
    session_id: str
    answers: List[AnswerItem]
