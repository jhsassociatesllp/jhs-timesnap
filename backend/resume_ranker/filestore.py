# backend/resume_ranker/filestore.py
"""
Where the CV files themselves live: MongoDB (GridFS, collection "CvFiles") in the
same Resume Ranker database as the records, so a redeploy, a new container or a
new server can never separate a record from its file.

Resumes uploaded before this change still have a `file_path` on disk; reads and
deletes fall back to it so they keep working.
"""
from __future__ import annotations

import os

import gridfs
from bson import ObjectId

from backend.resume_ranker.db import db

_fs = gridfs.GridFS(db, collection="CvFiles")


def save(data: bytes, filename: str) -> ObjectId:
    return _fs.put(data, filename=filename)


def read(resume: dict) -> bytes:
    """Bytes of the stored CV. Raises FileNotFoundError if it is gone."""
    fid = resume.get("file_id")
    if fid:
        try:
            return _fs.get(fid).read()
        except gridfs.errors.NoFile:
            raise FileNotFoundError("CV file is missing from the database")
    path = resume.get("file_path")
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read()
    raise FileNotFoundError("CV file is not available")


def has_file(resume: dict) -> bool:
    fid = resume.get("file_id")
    if fid:
        return _fs.exists(fid)
    path = resume.get("file_path")
    return bool(path and os.path.exists(path))


def delete(resume: dict) -> None:
    """Remove the CV and its cached PDF preview. Never raises."""
    for key in ("file_id", "preview_file_id"):
        if resume.get(key):
            try:
                _fs.delete(resume[key])
            except Exception:
                pass
    path = resume.get("file_path")
    if path:
        for p in (path, path + ".preview.pdf"):
            try:
                os.remove(p)
            except OSError:
                pass
