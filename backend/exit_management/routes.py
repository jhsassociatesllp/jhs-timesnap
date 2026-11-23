# backend/exit_management/routes.py
"""FastAPI routes for Employee Exit Management (all under /api/exit-management).

Every route identifies the employee from the login token (get_current_user);
an employee id sent by the browser is never used.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.auth import get_current_user
from backend.exit_management import approvals, hr_clearance, it_clearance, manager, notify, pdf_export, service, signature
from backend.exit_management.schemas import ExitFormPayload, HandoverPayload, HrPayload, ItPayload, RejectPayload

PREFIX = "/api/exit-management"
router = APIRouter(prefix=PREFIX, tags=["Employee Exit Management"])


class _SizeLimitedRoute(APIRoute):
    """Refuse an oversized upload from its Content-Length header BEFORE the request body is read/parsed."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > signature.MAX_BYTES + 64 * 1024:   # + multipart overhead
                return JSONResponse({"detail": "File is too large. Maximum size is 5 MB."}, status_code=413)
            return await original(request)

        return handler


upload_router = APIRouter(route_class=_SizeLimitedRoute)   # no prefix: included into `router`, which has it


def _empid(current_user: str) -> str:
    return current_user.strip().upper()


@router.get("/employee-details")
def employee_details(current_user: str = Depends(get_current_user)):
    return service.employee_details(_empid(current_user))


@router.get("/draft")
def get_draft(current_user: str = Depends(get_current_user)):
    return service.get_draft(_empid(current_user))


@router.post("/draft")
def save_draft(body: ExitFormPayload, current_user: str = Depends(get_current_user)):
    return service.save_draft(_empid(current_user), body)


@router.delete("/draft")
def delete_draft(current_user: str = Depends(get_current_user)):
    return service.delete_draft(_empid(current_user))


@router.post("/submit", status_code=201)
def submit(body: ExitFormPayload, background: BackgroundTasks, current_user: str = Depends(get_current_user)):
    result = service.submit(_empid(current_user), body)
    background.add_task(notify.exit_submitted, result["id"])                 # e-mail the Reporting Manager (after the save; never blocks it)
    return result


@router.get("/submission-status")
def submission_status(current_user: str = Depends(get_current_user)):
    return service.submission_status(_empid(current_user))


# ── Signature file (stored in MongoDB GridFS bucket `signature_files`) ─────────
@upload_router.post("/upload-signature", status_code=201)
def upload_signature(file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    """Upload (or replace) the signature: PDF / JPG / JPEG / PNG, max 5 MB."""
    return signature.upload_signature(_empid(current_user), file)


@router.get("/signature")
def get_signature(download: bool = False, current_user: str = Depends(get_current_user)):
    """The signed-in employee's own signature file (inline view, or ?download=true)."""
    return signature.get_signature(_empid(current_user), download)


@router.delete("/signature")
def delete_signature(current_user: str = Depends(get_current_user)):
    """Remove the signature from the employee's draft (never from a submitted form)."""
    return signature.delete_signature(_empid(current_user))


# -- Approval workflow: Reporting Manager -> IT -> HR -> Form Complete ----------
@router.get("/tracker")
def tracker(current_user: str = Depends(get_current_user)):
    """The employee's own approval status."""
    return approvals.tracker(_empid(current_user))


@router.get("/export-pdf")
def export_pdf(current_user: str = Depends(get_current_user)):
    """The employee's own exit form as one PDF (Exit Form, Project Details, IT Clearance, HR Clearance, with every signature drawn).
    Only once the whole exit process is complete."""
    data, name = pdf_export.build(_empid(current_user))
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/approver-status")
def approver_status(current_user: str = Depends(get_current_user)):
    """Which approval roles the signed-in employee has."""
    return approvals.roles(_empid(current_user))


@router.get("/approvals")
def approvals_queue(current_user: str = Depends(get_current_user)):
    """Forms waiting for an approval this employee may give."""
    return {"items": approvals.queue(_empid(current_user))}


@router.get("/approvals/{form_id}")
def approvals_review(form_id: str, current_user: str = Depends(get_current_user)):
    return approvals.review(_empid(current_user), form_id)


@router.post("/approvals/{form_id}/approve")
def approvals_approve(form_id: str, current_user: str = Depends(get_current_user)):
    return approvals.approve(_empid(current_user), form_id)


# -- Reporting Manager dashboard + Project Related Details (handover) form -------
# The manager is always the signed-in employee, verified against Employee_details on every call.
@router.get("/manager/dashboard")
def manager_dashboard(current_user: str = Depends(get_current_user)):
    return manager.dashboard(_empid(current_user))


@router.post("/manager/applications/{form_id}/approve")
def manager_approve(form_id: str, current_user: str = Depends(get_current_user)):
    """Approve the application: opens the project handover form (the stage completes when that form is submitted)."""
    return manager.approve(_empid(current_user), form_id)


@router.post("/manager/applications/{form_id}/reject")
def manager_reject(form_id: str, body: RejectPayload, current_user: str = Depends(get_current_user)):
    return manager.reject(_empid(current_user), form_id, body)


@router.get("/manager/applications/{form_id}/exit-form")
def manager_exit_form(form_id: str, current_user: str = Depends(get_current_user)):
    """The employee's filled exit form, read-only, for their Reporting Manager."""
    return manager.view_exit_form(_empid(current_user), form_id)


@router.get("/manager/applications/{form_id}/exit-form/signature")
def manager_exit_form_signature(form_id: str, download: bool = False, current_user: str = Depends(get_current_user)):
    return manager.exit_form_signature(_empid(current_user), form_id, download)


@router.get("/manager/applications/{form_id}/handover")
def handover_get(form_id: str, current_user: str = Depends(get_current_user)):
    return manager.get_handover(_empid(current_user), form_id)


@router.post("/manager/applications/{form_id}/handover/draft")
def handover_draft(form_id: str, body: HandoverPayload, current_user: str = Depends(get_current_user)):
    return manager.save_handover(_empid(current_user), form_id, body)


@router.post("/manager/applications/{form_id}/handover/submit", status_code=201)
def handover_submit(form_id: str, body: HandoverPayload, background: BackgroundTasks, current_user: str = Depends(get_current_user)):
    result = manager.submit_handover(_empid(current_user), form_id, body)
    background.add_task(notify.handover_submitted, form_id)                   # e-mail the IT representatives
    return result


@upload_router.post("/manager/applications/{form_id}/handover/signature/{row_key}", status_code=201)
def handover_signature_upload(form_id: str, row_key: str, file: UploadFile = File(...),
                              current_user: str = Depends(get_current_user)):
    """Upload (or replace) the signature file of ONE handover row: PDF / JPG / JPEG / PNG, max 5 MB, stored in GridFS."""
    return manager.upload_row_signature(_empid(current_user), form_id, row_key, file)


@router.delete("/manager/applications/{form_id}/handover/signature/{row_key}")
def handover_signature_remove(form_id: str, row_key: str, current_user: str = Depends(get_current_user)):
    return manager.remove_row_signature(_empid(current_user), form_id, row_key)


@router.get("/manager/applications/{form_id}/handover/signature/{row_key}")
def handover_signature_view(form_id: str, row_key: str, download: bool = False, current_user: str = Depends(get_current_user)):
    return manager.view_row_signature(_empid(current_user), form_id, row_key, download)


# -- IT Clearance (IT stage, for IT-team employees; done by their IT manager from `exit_approvers`) --
@router.get("/it/dashboard")
def it_dashboard(current_user: str = Depends(get_current_user)):
    return it_clearance.dashboard(_empid(current_user))


@router.post("/it/applications/{form_id}/reject")
def it_reject(form_id: str, body: RejectPayload, current_user: str = Depends(get_current_user)):
    return it_clearance.reject(_empid(current_user), form_id, body)


@router.get("/it/applications/{form_id}/clearance")
def it_get(form_id: str, current_user: str = Depends(get_current_user)):
    return it_clearance.get_form(_empid(current_user), form_id)


@router.post("/it/applications/{form_id}/clearance/draft")
def it_draft(form_id: str, body: ItPayload, current_user: str = Depends(get_current_user)):
    return it_clearance.save_draft(_empid(current_user), form_id, body)


@router.post("/it/applications/{form_id}/clearance/submit", status_code=201)
def it_submit(form_id: str, body: ItPayload, background: BackgroundTasks, current_user: str = Depends(get_current_user)):
    result = it_clearance.submit(_empid(current_user), form_id, body)
    background.add_task(notify.it_submitted, form_id)                        # e-mail the HR representatives
    return result


@upload_router.post("/it/applications/{form_id}/clearance/signature/{row_key}", status_code=201)
def it_signature_upload(form_id: str, row_key: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    return it_clearance.upload_row_signature(_empid(current_user), form_id, row_key, file)


@router.delete("/it/applications/{form_id}/clearance/signature/{row_key}")
def it_signature_remove(form_id: str, row_key: str, current_user: str = Depends(get_current_user)):
    return it_clearance.remove_row_signature(_empid(current_user), form_id, row_key)


@router.get("/it/applications/{form_id}/clearance/signature/{row_key}")
def it_signature_view(form_id: str, row_key: str, download: bool = False, current_user: str = Depends(get_current_user)):
    return it_clearance.view_row_signature(_empid(current_user), form_id, row_key, download)


# -- HR Clearance (HR stage, done by the HR manager - approvals.hr_managers) --
@router.get("/hr/dashboard")
def hr_dashboard(current_user: str = Depends(get_current_user)):
    return hr_clearance.dashboard(_empid(current_user))


@router.get("/hr/applications/{form_id}/exit-form")
def hr_exit_form(form_id: str, current_user: str = Depends(get_current_user)):
    """The employee's filled exit form, read-only, for the HR manager."""
    return hr_clearance.view_exit_form(_empid(current_user), form_id)


@router.get("/hr/applications/{form_id}/exit-form/signature")
def hr_exit_form_signature(form_id: str, download: bool = False, current_user: str = Depends(get_current_user)):
    return hr_clearance.exit_form_signature(_empid(current_user), form_id, download)


@router.get("/hr/applications/{form_id}/it-clearance")
def hr_it_clearance(form_id: str, current_user: str = Depends(get_current_user)):
    """The IT Clearance form of the employee, read-only, for the HR manager."""
    return hr_clearance.view_it_clearance(_empid(current_user), form_id)


@router.get("/hr/applications/{form_id}/it-clearance/signature/{row_key}")
def hr_it_clearance_signature(form_id: str, row_key: str, download: bool = False, current_user: str = Depends(get_current_user)):
    return it_clearance.view_row_signature(_empid(current_user), form_id, row_key, download)


@router.get("/hr/applications/{form_id}/handover")
def hr_handover(form_id: str, current_user: str = Depends(get_current_user)):
    """The Project Details (handover) form, read-only, for the HR manager."""
    return hr_clearance.view_handover(_empid(current_user), form_id)


@router.get("/hr/applications/{form_id}/handover/signature/{row_key}")
def hr_handover_signature(form_id: str, row_key: str, download: bool = False, current_user: str = Depends(get_current_user)):
    return manager.view_row_signature(_empid(current_user), form_id, row_key, download)


@router.get("/hr/applications/{form_id}/export-pdf")
def hr_export_pdf(form_id: str, current_user: str = Depends(get_current_user)):
    """The same exit-form PDF the employee gets, for an HR representative, once the exit process is complete."""
    data, name = pdf_export.build_for_hr(_empid(current_user), form_id)
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/hr/applications/{form_id}/reject")
def hr_reject(form_id: str, body: RejectPayload, current_user: str = Depends(get_current_user)):
    return hr_clearance.reject(_empid(current_user), form_id, body)


@router.get("/hr/applications/{form_id}/clearance")
def hr_get(form_id: str, current_user: str = Depends(get_current_user)):
    return hr_clearance.get_form(_empid(current_user), form_id)


@router.post("/hr/applications/{form_id}/clearance/draft")
def hr_draft(form_id: str, body: HrPayload, current_user: str = Depends(get_current_user)):
    return hr_clearance.save_draft(_empid(current_user), form_id, body)


@router.post("/hr/applications/{form_id}/clearance/submit", status_code=201)
def hr_submit(form_id: str, body: HrPayload, background: BackgroundTasks, current_user: str = Depends(get_current_user)):
    result = hr_clearance.submit(_empid(current_user), form_id, body)
    background.add_task(notify.exit_completed, form_id)                      # e-mail the employee: the exit process is completed
    return result


@upload_router.post("/hr/applications/{form_id}/clearance/signature/{slot}", status_code=201)
def hr_signature_upload(form_id: str, slot: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    return hr_clearance.upload_signature(_empid(current_user), form_id, slot, file)


@router.delete("/hr/applications/{form_id}/clearance/signature/{slot}")
def hr_signature_remove(form_id: str, slot: str, current_user: str = Depends(get_current_user)):
    return hr_clearance.remove_signature(_empid(current_user), form_id, slot)


@router.get("/hr/applications/{form_id}/clearance/signature/{slot}")
def hr_signature_view(form_id: str, slot: str, download: bool = False, current_user: str = Depends(get_current_user)):
    return hr_clearance.view_signature(_empid(current_user), form_id, slot, download)


router.include_router(upload_router)
