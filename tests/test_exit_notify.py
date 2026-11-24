"""E-mail notifications of the exit workflow (Graph sending is replaced by a recorder; nothing is ever sent)."""
import pytest

from backend.exit_management import notify
from tests.test_exit_approvals import hr_pass, it_pass, manager_pass, submit_as  # noqa: F401
from tests.test_exit_hr_clearance import hr  # noqa: F401
from tests.test_exit_management import EMPLOYEES, U, api  # noqa: F401

MAIL_OF = {"T001": "t001@jhs.test", "M001": "m001@jhs.test", "JHS722": "it722@jhs.test", "JHS1474": "it1474@jhs.test", "JHS1551": "it1551@jhs.test",
           "JHS1423": "hr1423@jhs.test", "JHS911": "hr911@jhs.test"}


@pytest.fixture()
def mail(hr, monkeypatch):
    """Mail switched ON with dummy settings; every message is recorded instead of sent."""
    for k, v in (("TENANT_AP", "tenant"), ("CLIENT_AP", "client"), ("CLIENT_SECRET_AP", "secret"), ("SENDER_AP", "sender@jhs.test")):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("EXIT_MAIL_DISABLED", raising=False)
    for code, address in MAIL_OF.items():
        EMPLOYEES.setdefault(code, {"EmpID": code, "Emp Name": code})["EMail"] = address
    EMPLOYEES["JHS911"] = {"EmpID": "JHS911", "Emp Name": "Hr Exec", "EMail": MAIL_OF["JHS911"], "ReportingEmpCode": "JHS1423"}
    sent = []
    monkeypatch.setattr(notify, "_send_graph", lambda to, subject, body: sent.append((to, subject, body)))
    hr.sent = sent
    yield hr
    for code in MAIL_OF:
        if code in EMPLOYEES:
            EMPLOYEES[code].pop("EMail", None)
    EMPLOYEES.pop("JHS911", None)


def take(client):
    out = list(client.sent)
    client.sent.clear()
    return out


def test_the_four_steps_send_the_right_mails_in_order(mail):
    # 1) the employee submits the exit form -> the Reporting Manager
    fid = submit_as(mail, "T001")
    m = take(mail)
    assert [x[0] for x in m] == ["m001@jhs.test"]
    assert "T001" in m[0][1] and "Exit form submitted" in m[0][1] and "T001" in m[0][2] and "https://jhstimesnap.in/" in m[0][2] and "Log in to JHS Timesnap" in m[0][2]
    # 2) the Reporting Manager submits Project Details -> every IT representative
    manager_pass(mail, fid)
    m = take(mail)
    assert sorted(x[0] for x in m) == ["it1474@jhs.test", "it1551@jhs.test", "it722@jhs.test"]
    assert all("IT Clearance needed" in x[1] and "https://jhstimesnap.in/" in x[2] for x in m)
    # 3) IT submits the IT Clearance -> every HR representative
    it_pass(mail, fid)
    m = take(mail)
    assert sorted(x[0] for x in m) == ["hr1423@jhs.test", "hr911@jhs.test"]
    assert all("HR Clearance needed" in x[1] and "https://jhstimesnap.in/" in x[2] for x in m)
    # 4) HR submits the HR Clearance -> the employee: the exit process is completed
    hr_pass(mail, fid)
    m = take(mail)
    assert [x[0] for x in m] == ["t001@jhs.test"]
    assert m[0][1] == "Your exit process is completed" and "Exit Status Tracker" in m[0][2] and "https://jhstimesnap.in/" in m[0][2]
    assert take(mail) == []


def test_no_mail_before_the_save_succeeds_or_when_a_step_is_refused(mail):
    mail.as_user("T001")
    r = mail.post(f"{U}/submit", json={})                                       # incomplete form: refused, nothing saved
    assert r.status_code in (404, 409, 422)
    assert take(mail) == []
    fid = submit_as(mail, "T001")
    take(mail)
    mail.as_user("M001")
    assert mail.post(f"{U}/manager/applications/{fid}/handover/submit", json={"items": []}).status_code in (409, 422)   # no handover started / incomplete
    mail.as_user("JHS722")
    assert mail.post(f"{U}/it/applications/{fid}/clearance/submit", json={"items": []}).status_code in (403, 409, 422)  # not IT's turn
    assert take(mail) == []


def test_a_mail_failure_or_a_missing_address_never_breaks_the_workflow(mail, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Graph is down")
    monkeypatch.setattr(notify, "_send_graph", boom)
    fid = submit_as(mail, "T001")                                               # still saved and returns 201 (submit_as asserts it)
    assert mail.col.find_one({"employee_id": "T001"})["status"] == "submitted"
    manager_pass(mail, fid)
    EMPLOYEES["M002"].pop("EMail", None)
    EMPLOYEES["M002"].pop("Personal EMail", None)
    submit_as(mail, "T004")                                                     # T004's manager M002 has no e-mail address: skipped quietly
    assert mail.col.find_one({"employee_id": "T004"})["status"] == "submitted"


def test_mail_is_switched_off_without_settings_or_with_the_disable_flag(mail, monkeypatch):
    monkeypatch.setenv("EXIT_MAIL_DISABLED", "1")
    submit_as(mail, "T001")
    assert take(mail) == []                                                     # flag on: the sender is never called
    monkeypatch.delenv("EXIT_MAIL_DISABLED")
    monkeypatch.delenv("CLIENT_SECRET_AP")
    assert notify.enabled() is False
    mail.col.delete_many({})
    submit_as(mail, "T001")
    assert take(mail) == []                                                     # a missing setting: nothing sent, nothing breaks


def test_no_manager_on_record_goes_to_the_hr_representatives(mail):
    submit_as(mail, "T002")                                                     # T002 has no Reporting Manager in the stub data
    EMPLOYEES["T002"]["EMail"] = "t002@jhs.test"
    assert sorted(x[0] for x in take(mail)) == ["hr1423@jhs.test", "hr911@jhs.test"]
    EMPLOYEES["T002"].pop("EMail", None)


def test_only_the_official_email_is_used_never_the_personal_one(mail):
    EMPLOYEES["M001"]["Personal EMail"] = "m001.personal@gmail.test"
    submit_as(mail, "T001")
    assert [x[0] for x in take(mail)] == ["m001@jhs.test"]                       # EMail, not Personal EMail
    EMPLOYEES["M001"].pop("EMail")                                               # no official address: skipped, the personal one is NOT used
    mail.col.delete_many({})
    submit_as(mail, "T001")
    assert take(mail) == []
    EMPLOYEES["M001"].pop("Personal EMail")
    EMPLOYEES["M001"]["EMail"] = MAIL_OF["M001"]


def test_the_login_link_can_be_overridden_by_a_setting(mail, monkeypatch):
    monkeypatch.setenv("EXIT_MAIL_LOGIN_URL", "https://other.example/")
    submit_as(mail, "T001")
    m = take(mail)
    assert "https://other.example/" in m[0][2] and "https://jhstimesnap.in/" not in m[0][2]


def test_addresses_pasted_with_mailto_names_or_several_values_are_cleaned():
    assert notify.clean_address("mailto:ramakrishnan.sundar@jhsassociates.in") == "ramakrishnan.sundar@jhsassociates.in"
    assert notify.clean_address("  Pankaj Gupta <pankaj.gupta@jhsassociates.in> ") == "pankaj.gupta@jhsassociates.in"
    assert notify.clean_address("a.b@jhsassociates.in; c.d@jhsassociatesllp.in") == "a.b@jhsassociates.in"
    assert notify.clean_address("O'Neil@jhsassociates.in\u00a0") == "O'Neil@jhsassociates.in"
    assert notify.clean_address("not an address") == "" and notify.clean_address(None) == "" and notify.clean_address("") == ""


def test_a_mailto_address_on_record_still_receives_the_mail(mail):
    EMPLOYEES["JHS1551"]["EMail"] = "mailto:it1551@jhs.test"
    fid = submit_as(mail, "T001")
    take(mail)
    manager_pass(mail, fid)
    assert sorted(x[0] for x in take(mail)) == ["it1474@jhs.test", "it1551@jhs.test", "it722@jhs.test"]   # the cleaned address, not "mailto:..."
