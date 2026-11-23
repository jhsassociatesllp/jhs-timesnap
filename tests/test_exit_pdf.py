"""Exit Form PDF: only when the exit process is complete; sections in order; every signature drawn as an image (throwaway database zz_exit_test)."""
import io
import re

from pypdf import PdfReader

from tests.test_exit_approvals import hr_pass, it_pass, manager_pass, submit_as  # noqa: F401
from tests.test_exit_hr_clearance import hr  # noqa: F401
from tests.test_exit_management import EMPLOYEES, PDF, U, api  # noqa: F401


def pages_text(data: bytes):
    reader = PdfReader(io.BytesIO(data))
    return reader, [p.extract_text() for p in reader.pages]


def test_pdf_is_refused_until_the_exit_process_is_complete(hr):
    hr.as_user("T001")
    assert hr.get(f"{U}/export-pdf").status_code == 404                        # nothing submitted yet
    fid = submit_as(hr)
    assert hr.get(f"{U}/export-pdf").status_code == 409                        # Reporting Manager pending
    manager_pass(hr, fid)
    hr.as_user("T001")
    assert hr.get(f"{U}/export-pdf").status_code == 409                        # IT pending
    it_pass(hr, fid)
    hr.as_user("T001")
    assert hr.get(f"{U}/export-pdf").status_code == 409                        # HR pending
    hr_pass(hr, fid)
    hr.as_user("T001")
    r = hr.get(f"{U}/export-pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="Employee_Exit_Form_T001.pdf"' in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"


def test_pdf_has_the_four_sections_in_order_with_real_signature_images(hr):
    fid = submit_as(hr)
    manager_pass(hr, fid)
    it_pass(hr, fid)
    hr_pass(hr, fid)
    hr.as_user("T001")
    data = hr.get(f"{U}/export-pdf").content
    reader, texts = pages_text(data)
    joined = "\n".join(texts)
    order = [joined.index(t) for t in ("1. Employee Exit Form", "2. Project Details", "3. IT Clearance", "4. HR Clearance")]
    assert order == sorted(order)                                              # Exit Form, Project Details, IT Clearance, HR Clearance
    assert "Test One" in joined and "T001" in joined and "Served Notice Period" in joined and "JHS Laptop Returned" in joined
    assert "Project Related Details Handover" in joined and "I hereby declare that I haven't joined any of JHS Client" in joined
    assert "17. Would you rejoin JHS" in joined and "Communication" in joined and "All clear" in joined      # answers, ratings, HR comments
    assert "View" not in joined                                                # no "view signature" links
    images = sum(len(re.findall(rb'/\S+\s+Do', p.get_contents().get_data())) for p in reader.pages)     # image placements
    # the Signature columns now say "Signed" (19 rows: 4 handover + 12 IT + 3 HR); the real images are the signature boxes
    assert joined.count("Signed") >= 19
    assert "Reporting Manager Signature" in joined and "IT Representative Signature" in joined and "HR Signature" in joined and not re.search(r"HR Sign(?!ature)", joined)
    assert images == 5, images          # employee (exit form) + RM box + IT box + employee + HR signature (HR page)


def test_each_employee_only_gets_their_own_pdf_and_a_pdf_signature_is_drawn_as_an_image(hr):
    fid = submit_as(hr)
    manager_pass(hr, fid)
    # IT signs with a PDF file: the PDF export shows its first page as an image
    hr.as_user("JHS722")
    base = f"{U}/it/applications/{fid}/clearance"
    assert hr.get(base).status_code == 200
    keys = ["jhs_laptop", "jhs_email_disabled", "client_laptop", "client_email_disabled", "nexus_quant_id", "msb_portal_id",
            "work_data_handover", "personal_email_removed", "mobile_sim", "biometric_access", "hardware_devices", "other_it_assets"]
    from tests.test_exit_it_clearance import sig as it_sig
    assert it_sig(hr, fid, "jhs_laptop", PDF, "sign.pdf", "application/pdf").status_code == 201           # a PDF signature
    for k in keys[1:]:
        assert it_sig(hr, fid, k).status_code == 201                                                       # every Yes row needs one
    assert hr.post(f"{base}/submit", json={"items": [{"key": k, "option": "Yes", "remarks": ""} for k in keys]}).status_code == 201
    hr_pass(hr, fid)
    hr.as_user("T005")
    assert hr.get(f"{U}/export-pdf").status_code == 404                        # T005 has no exit form: never somebody else's
    hr.as_user("T001")
    assert hr.get(f"{U}/export-pdf").status_code == 200


def test_hr_representative_gets_the_same_pdf_for_a_completed_form_only(hr):
    fid = submit_as(hr)
    manager_pass(hr, fid)
    it_pass(hr, fid)
    for who in ("JHS1423", "JHS911"):
        hr.as_user(who)
        assert hr.get(f"{U}/hr/applications/{fid}/export-pdf").status_code == 409          # HR stage not finished yet
    hr_pass(hr, fid)
    hr.as_user("T001")
    own = hr.get(f"{U}/export-pdf")
    assert own.status_code == 200
    for who in ("JHS1423", "JHS911"):
        hr.as_user(who)
        r = hr.get(f"{U}/hr/applications/{fid}/export-pdf")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        assert 'filename="Employee_Exit_Form_T001.pdf"' in r.headers["content-disposition"]
        assert [p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages] == [p.extract_text() for p in PdfReader(io.BytesIO(own.content)).pages]   # one format
    for who in ("T001", "T005", "M001", "X999", "JHS722", "JHS1191"):
        hr.as_user(who)
        assert hr.get(f"{U}/hr/applications/{fid}/export-pdf").status_code == 403, who
    hr.as_user("JHS1423")
    assert hr.get(f"{U}/hr/applications/{'0' * 24}/export-pdf").status_code == 404


def test_pdf_shows_the_q23_reason_only_when_the_answer_was_no(hr):
    for answer, reason, shown in (("No", "Too little growth for juniors", True), ("Yes", "", False)):
        hr.col.delete_many({})
        hr.files.delete_many({})
        hr.as_user("T001")
        from tests.test_exit_management import full_form, upload
        assert upload(hr).status_code == 201
        body = full_form()
        body["exit_interview"]["recommend_company"] = answer
        body["exit_interview"]["recommend_reason"] = reason
        assert hr.post(f"{U}/submit", json=body).status_code == 201
        fid = str(hr.col.find_one({"employee_id": "T001"})["_id"])
        manager_pass(hr, fid)
        it_pass(hr, fid)
        hr_pass(hr, fid)
        hr.as_user("T001")
        _, texts = pages_text(hr.get(f"{U}/export-pdf").content)
        joined = "\n".join(texts)
        assert ("Reason for not recommending the company" in joined) is shown
        assert ("Too little growth for juniors" in joined) is shown
        hr.as_user("JHS1423")                                                      # the HR copy is the same document
        _, hr_texts = pages_text(hr.get(f"{U}/hr/applications/{fid}/export-pdf").content)
        assert "\n".join(hr_texts) == joined
