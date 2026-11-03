import re
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


def _split_and_dedup_emails(v):
    if isinstance(v, str):
        items = re.split(r"[\s,;]+", v)
    elif isinstance(v, (list, tuple, set)):
        items = []
        for item in v:
            if isinstance(item, str):
                items.extend(re.split(r"[\s,;]+", item))
            else:
                items.append(item)
    else:
        return v
    res, seen = [], set()
    for x in items:
        s = str(x).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            res.append(s)
    return res


class CandidateLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AddCandidatesRequest(BaseModel):
    # One per line or comma separated in the UI, parsed into a list before hitting the API.
    emails: List[EmailStr]
    quiz_set_id: str

    @field_validator("emails", mode="before")
    @classmethod
    def parse_emails(cls, v):
        return _split_and_dedup_emails(v)


class QuizSetDocumentEntry(BaseModel):
    document_id: str
    count: int = Field(gt=0, le=200)


class CreateQuizSetRequest(BaseModel):
    name: str = Field(min_length=1)
    documents: List[QuizSetDocumentEntry] = Field(min_length=1)


class UpdateQuizSetRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    documents: Optional[List[QuizSetDocumentEntry]] = Field(default=None, min_length=1)


class RegeneratePasswordRequest(BaseModel):
    emails: List[EmailStr]

    @field_validator("emails", mode="before")
    @classmethod
    def parse_emails(cls, v):
        return _split_and_dedup_emails(v)


class AnswerItem(BaseModel):
    question_id: str
    selected_option: Optional[int] = None  # index 0-3, null if not attempted in time
    time_taken_seconds: float = 0


class SubmitQuizRequest(BaseModel):
    session_id: str
    answers: List[AnswerItem]
