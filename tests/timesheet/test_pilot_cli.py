import os
import socket

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from pymongo import MongoClient

from backend.cycle.store import store
from backend.timesheet import pilot

PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))


def _up():
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


@pytest.fixture
def cfg(monkeypatch):
    if not _up():
        pytest.skip("dev Mongo not running")
    coll = MongoClient(f"mongodb://127.0.0.1:{PORT}/")["timesnap_test"]["p_config"]
    coll.drop()
    monkeypatch.setattr(store, "config", coll)
    return coll


def test_add_remove_list(cfg, capsys):
    assert pilot.main(["list"]) == 0 and "(none)" in capsys.readouterr().out
    assert pilot.main(["add", "jhs1234", " JHS5678 "]) == 0
    assert pilot.current() == ["JHS1234", "JHS5678"]
    assert pilot.main(["add", "JHS1234"]) == 0 and pilot.current() == ["JHS1234", "JHS5678"]        # no duplicates
    assert pilot.main(["remove", "JHS1234"]) == 0 and pilot.current() == ["JHS5678"]
    assert cfg.find_one({"_id": "timesheet"})["pilot_employees"] == ["JHS5678"]


def test_bad_codes_and_usage_change_nothing(cfg, capsys):
    pilot.add(["JHS1"])
    for bad in (["add", "JHS 1; drop"], ["add", "{$ne:1}"], ["add", "x"], ["remove", "$"]):
        assert pilot.main(bad) == 2
    assert pilot.main([]) == 2 and pilot.main(["add"]) == 2 and pilot.main(["nope", "JHS1"]) == 2
    assert pilot.current() == ["JHS1"]


def test_include_and_scope_commands(cfg, capsys):
    assert pilot.main(["include", "jhs1191"]) == 0 and pilot.current_include() == ["JHS1191"]
    assert pilot.main(["include", "JHS1191"]) == 0 and pilot.current_include() == ["JHS1191"]      # no duplicates
    assert pilot.main(["list"]) == 0 and "JHS1191" in capsys.readouterr().out
    assert pilot.main(["include", "bad code!"]) == 2 and pilot.current_include() == ["JHS1191"]
    assert pilot.main(["uninclude", "JHS1191"]) == 0 and pilot.current_include() == []
    assert pilot.main(["scope", "pilot"]) == 0 and cfg.find_one({"_id": "timesheet"})["timesheet_scope"] == "pilot"
    assert pilot.main(["scope", "nope"]) == 2
