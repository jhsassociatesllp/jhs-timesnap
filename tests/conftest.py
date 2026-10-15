"""Test setup for the Resume Ranker module: mongomock instead of a real MongoDB,
and a scripted fake OpenAI client instead of the network."""
import hashlib
import json
import os
import re
import sys
import types

import mongomock
import pymongo

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27017")
os.environ.setdefault("SECRET_KEY", "test-secret")
pymongo.MongoClient = mongomock.MongoClient          # must happen before backend.* is imported
from mongomock import gridfs as _mgridfs
_mgridfs.enable_gridfs_integration()                 # CV files are stored in GridFS
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


class FakeOpenAI:
    """Answers parse / score / extract calls from a table keyed on resume text,
    so tests control exactly what the 'model' says."""

    EMBED_DIM = 64

    def __init__(self):
        self.calls = []
        self.embed_calls = []
        self.parse_by_marker = {}       # marker text in resume -> parsed JSON
        self.judge_by_marker = {}       # marker text in profile -> judgement JSON
        self.fail_transient = 0
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
        self.embeddings = types.SimpleNamespace(create=self._embed)

    def _embed(self, **kw):
        """Deterministic hashing-trick bag-of-words vector — no real API call,
        but texts sharing more words genuinely get higher cosine similarity,
        so tests can rely on realistic ranking behaviour."""
        text = kw["input"]
        self.embed_calls.append(text)
        vec = [0.0] * self.EMBED_DIM
        for word in re.findall(r"[a-z0-9+#]+", text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.EMBED_DIM] += 1.0
        item = types.SimpleNamespace(embedding=vec)
        return types.SimpleNamespace(data=[item])

    def _create(self, **kw):
        system = kw["messages"][0]["content"]
        user = kw["messages"][1]["content"]
        self.calls.append((system[:30], user))
        if self.fail_transient > 0:
            self.fail_transient -= 1
            err = RuntimeError("rate limited")
            err.status_code = 429
            raise err
        if "resume parser" in system:
            table = self.parse_by_marker
        elif "recruiter's assistant" in system:
            table = self.judge_by_marker
        else:
            table = {"JOBDESC": {"title": "Auditor", "required_skills": ["Audit", "Tally"], "min_years": 3,
                                 "education_level": "professional", "required_certifications": ["CA"]}}
        payload = next((v for k, v in table.items() if k in user), {})
        msg = types.SimpleNamespace(content=json.dumps(payload))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])


@pytest.fixture
def fake_llm():
    from backend.resume_ranker import llm
    fake = FakeOpenAI()
    llm.set_client(fake)
    yield fake
    llm.set_client(None)


@pytest.fixture
def clean_db(tmp_path, monkeypatch):
    from backend.resume_ranker import db
    monkeypatch.setenv("RESUME_UPLOAD_DIR", str(tmp_path / "uploads"))
    for coll in (db.jobs, db.resumes, db.scores, db.batches, db.tasks, db.db['CvFiles.files'], db.db['CvFiles.chunks']):
        coll.delete_many({})
    yield
