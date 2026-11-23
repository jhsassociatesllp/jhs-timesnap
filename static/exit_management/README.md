# Employee Exit Management module

Clearance form + exit interview for a leaving employee. Self-contained: everything lives in
`backend/exit_management/` and `static/exit_management/`.

## Files

| Path | Purpose |
|---|---|
| `backend/exit_management/routes.py` | FastAPI routes (`/api/exit-management/...`) |
| `backend/exit_management/schemas.py` | Pydantic models (what the browser may send) |
| `backend/exit_management/service.py` | Rules: employee details, drafts, validation, atomic submit |
| `backend/exit_management/repository.py` | MongoDB access + indexes (reuses `backend.database`) |
| `backend/exit_management/utils.py` | Date conversion, ObjectId/datetime -> JSON |
| `backend/exit_management/manager.py` | Reporting Manager dashboard, approve/reject, project handover form + per-row signatures |
| `backend/exit_management/approvals.py` | Approval workflow (Reporting Manager -> IT -> HR -> Form Complete) |
| `backend/exit_management/signature.py` | Signature file upload / view / remove (GridFS) + pre-submit check |
| `static/exit_management/employee_exit.html` | The ONE single-page form (one `<form>`, 5 sections; section 5 is the signature file upload), served at `/exit-management` |
| `static/exit_management/tracker.html` + `js/tracker.js` | Exit Status Tracker (employee, after submitting) |
| `static/exit_management/manager.html` + `js/manager.js` | Reporting Manager dashboard (details, team, exit applications, Approve / Reject) |
| `static/exit_management/handover.html` + `js/handover.js` | Project Related Details (handover) form: 4 rows, each with Yes/No, remarks and its own signature upload |
| `static/exit_management/css/manager.css` | Styles for those two pages |
| `static/exit_management/approvals.html` + `js/approvals.js` | Approvals page for Reporting Managers / IT / HR |
| `static/exit_management/css/employee_exit.css` | Styles for this module only |
| `static/exit_management/js/` | `validation.js` (questions + checks), `employee_details.js` (API helper, file upload, Section A), `signature.js` (file upload UI), `draft.js`, `employee_exit.js` (wiring) |
| `tests/test_exit_management.py` | 65 API tests (`test_exit_management.py`, `test_exit_approvals.py`, `test_exit_manager.py`) (throwaway database) |

## Existing files touched (integration only)

* `main.py` - import + `include_router`, the pages `/exit-management` (the form), `/exit-management/tracker`, `/exit-management/approvals`, `/exit-management/manager`, `/exit-management/handover`, no-cache path list.
* `static/modules.html` - the module card (CSS + card + one `shown('exit_management')` line).
* `backend/access_manager/router.py` - one `PAGE_MODULES` entry so owners can hide/show the card.

## API (all need the normal login token; the employee is taken from the token, never from the request)

| Method | Path | |
|---|---|---|
| GET | `/api/exit-management/employee-details` | Section A from `Employee_details` |
| GET | `/api/exit-management/draft` | saved draft (or the submitted form) |
| POST | `/api/exit-management/draft` | create/update draft |
| DELETE | `/api/exit-management/draft` | delete own draft (never a submitted form) |
| POST | `/api/exit-management/submit` | validate + submit (201; 422 lists what is missing; 409 if already submitted) |
| GET | `/api/exit-management/submission-status` | `none` / `draft` / `submitted` |
| POST | `/api/exit-management/upload-signature` | multipart `file`: PDF/JPG/JPEG/PNG, max 5 MB. Replaces the draft's previous signature (old file deleted after the new one is saved). 413/415/400 for too large / wrong type / empty |
| GET | `/api/exit-management/signature` | the employee's own signature file (`?download=true` to download) |
| DELETE | `/api/exit-management/signature` | remove the signature from the DRAFT (409 once submitted) |

Signature files: stored in the GridFS bucket **`signature_files`** (same shared `Timesheets` database), never as Base64 in `exist_form`.
`exist_form.signature_file` = `{gridfs_file_id, filename, content_type, file_size, extension, uploaded_at}`; the GridFS file's
metadata holds `employee_id`, `form_id` (the exist_form `_id`), `original_filename`, `content_type`, `extension`, `uploaded_at`.
The server checks the real file content (PDF/JPEG/PNG signature bytes, images must decode), that the extension and declared type match,
and streams the file in 256 KB chunks. Submit re-checks that the GridFS file exists, belongs to the employee and this form, and is <= 5 MB.
The signature of a submitted form is never deleted. There is no PDF export of the form any more.

PDF file name: `Employee_Exit_Form_<employee code>.pdf`. The built-in PDF fonts are Latin-1 only, so characters outside it (e.g. Devanagari, emoji) print as `?` in the PDF; the data in MongoDB is unaffected.

## MongoDB

Database `Timesheets` (the shared one), collection **`exist_form`** (name as requested), ONE document per employee:
`employee_id`, `employee_name`, `employee_details{code, designation, joining_date, reporting_to, resignation_date, last_working_date}`,
`manager_feedback{8}`, `company_feedback{8}`, `exit_interview{...}`, `signature` (PNG data URL),
`status` (`draft` | `submitted`), `created_at`, `updated_at`, `submitted_at`.
Indexes: unique `employee_id`, plain `status`.

Draft and submission are the same document: submit changes `draft` -> `submitted` in a single atomic
`find_one_and_update` (filter `status: "draft"`). The unique index makes a second submit, or overwriting a
submitted form, fail with 409, so there is no leftover draft and no duplicate.

Employee details (name, code, designation, joining date, reporting manager) come from `Employee_details`
(`Emp Name`, `EmpID`, `Designation Name`, `Date of Joining`, `ReportingEmpName`). Resignation and last working
date are not stored there, so the employee enters them.

Q22 (pull factors) and the employer name are required only when Q21 "better prospect" is Yes.

## Run

```powershell
cd "F:\Aditya\Timesheet App\jhs-timesnap"
.\start_server.bat          # or: .\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001
```
Open http://127.0.0.1:8001/login, log in, choose **Employee Exit Management**.
The frontend is served by the same app, so there is no separate frontend server.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_exit_management.py --noconftest -q
```
Uses the throwaway database `zz_exit_test` (not the real `exist_form`).


## After submitting: approval workflow

Submit -> success popup "Employee Exit Form Submitted Successfully!" -> closing it opens **/exit-management/tracker**.
Opening `/exit-management` again after submitting also goes straight to the tracker (the submitted form is never shown again).

`Reporting Manager -> IT -> HR -> Form Complete`. A stage can only be approved while it is the current one.
Stored in the same `exist_form` document as an `approval` object:

```
approval: {
  current_stage: "reporting_manager" | "it" | "hr" | "complete",
  reporting_manager: {status: "pending"|"approved", expected_approver_code, expected_approver_name,
                      approver_code, approver_name, pending_since, approved_at},
  it:  {status, approver_code, approver_name, pending_since, approved_at},
  hr:  {status, approver_code, approver_name, pending_since, approved_at},
  form_complete: {status, completed_at}
}
```

| Method | Path | Who |
|---|---|---|
| GET | `/api/exit-management/tracker` | the employee (own form) |
| GET | `/api/exit-management/approver-status` | anyone (which roles do I have?) |
| GET | `/api/exit-management/approvals` | approvers: forms waiting for me |
| GET | `/api/exit-management/approvals/{form_id}` | approvers: review (feedback sections only for HR) |
| POST | `/api/exit-management/approvals/{form_id}/approve` | approves the CURRENT stage if I am authorised |

Who can approve:
* **Reporting Manager** - the code in the employee's own record (`ReportingEmpCode`), saved on the form at submit time.
  If the record has none, HR approvers may approve that stage.
* **IT / HR** - the people in the MongoDB collection **`exit_approvers`** (database `Timesheets`), one document each:
  `{ "stage": "it", "empid": "JHS123" }` or `{ "stage": "hr", "empid": "JHS456" }` (add them in Compass), plus the owners
  JHS1191 and JHS1485 (`EXIT_ADMINS` in `approvals.py`), who can always approve IT and HR.
* Nobody can approve their own form, even if they are an approver.
* Privacy: the ratings and interview answers are shown only to HR approvers, not to the reporting manager or IT.


## Reporting Manager dashboard + project handover (the Reporting Manager stage in detail)

`/exit-management/manager` - detected automatically: you are a Reporting Manager when other employees have your employee code in
`Employee_details.ReportingEmpCode` (nothing hardcoded; the browser never says who the manager is). Managers with applications waiting are
taken there when they open Employee Exit Management (once per browser session); everyone with a team also gets a "Manager Dashboard"
button in the navbar.

1. **Reporting Manager Details** - name, ID, designation, branch, team size from `Employee_details`.
   (There is no Department field: the employee data has none, so the dashboard does not show one.)
2. **My Team Members** - everyone whose `ReportingEmpCode` is you (never yourself).
3. **Employee Exit Applications** - only SUBMITTED forms of that team, with Approve / Reject.

Flow: `Pending -> Reject (reason required)` = stage **Rejected**, nothing goes to IT/HR, the employee's tracker shows Rejected + the reason.
`Pending -> Approve` opens the **Project Related Details** form (`/exit-management/handover?form=<id>`); the Reporting Manager stage stays
Pending until that form is SUBMITTED (all four rows need Yes/No + their own signature file). Then the stage becomes **Approved** and IT becomes Pending.

Stored in the employee's own `exist_form` document:
```
approval.reporting_manager: {status: pending|approved|rejected, decision: pending|approved|rejected, decided_at, decided_by_code/name,
                             rejection_reason, rejected_at, approver_code/name, approved_at, pending_since, expected_approver_*}
approval.current_stage: reporting_manager | it | hr | complete | rejected
project_handover: {status: draft|submitted, created_at, submitted_at, submitted_by,
                   items: [{key, particular, option: Yes|No, remarks, signature_file: {gridfs_file_id, filename, content_type, file_size, extension, uploaded_at}}] x 4}
```
Each row's signature file is a GridFS file in `signature_files` (metadata: employee_id, form_id, kind="handover", row_key, uploaded_by, ...), PDF/JPG/JPEG/PNG, max 5 MB,
removable per row until the form is submitted; the files are kept after submission. The manager is verified in MongoDB on every call (live `ReportingEmpCode`
of the employee), so another manager, the employee, or anyone else gets 403.

| Method | Path |
|---|---|
| GET | `/api/exit-management/manager/dashboard` |
| POST | `/api/exit-management/manager/applications/{id}/approve` |
| POST | `/api/exit-management/manager/applications/{id}/reject`  `{ "reason": "..." }` |
| GET | `/api/exit-management/manager/applications/{id}/handover` |
| POST | `.../handover/draft`  `{ "items": [{ "key", "option", "remarks" }] }` |
| POST / GET / DELETE | `.../handover/signature/{row_key}` (upload / view / remove one row's signature) |
| POST | `.../handover/submit` |

Row keys: `confidential_files`, `project_handover`, `induction`, `other_comments`.
The generic `/approvals/{id}/approve` no longer works for the Reporting Manager stage (it is IT / HR only).

## IT Clearance (the IT stage, for IT-team employees)

The paper form's "Information Technology" table: Laptop / System, Company Software and ID Card, Email ID Deletion,
Hardware (CD's, Hard ware, Pendrives, biometric etc.) - each row with Yes/No, remarks and its own signature file (GridFS, PDF/JPG/JPEG/PNG, 5 MB).

**Who is the IT manager / IT team** - by employee ID, in `IT_MANAGER_TEAMS` in `backend/exit_management/approvals.py`
(the employee data has no department field, so nothing is derived from it): `JHS722` is the IT manager, `JHS1474` and `JHS1551` are his juniors.
No database record is needed. More people can be added in the `exit_approvers` collection (combined with the list in code):
```
{ "stage": "it", "empid": "JHS722", "team": ["JHS1474", "JHS1551"] }
```
* For an employee listed in some `team`, ONLY that IT manager can complete the IT stage (owners and general IT approvers cannot), and only through the IT Clearance form. The one-click `/approvals/{id}/approve` answers 409 for them.
* An IT row **without** `team` is a general IT approver, exactly as before (all other employees keep the old one-click IT approval). A row with `team` is not a general approver.

Flow: Reporting Manager approves + handover submitted -> IT Clearance **Pending** -> IT manager opens `/exit-management/it-clearance`,
Open IT Clearance (`/exit-management/it-form?form=<id>`) -> Submit -> IT **Approved**, HR **Pending**. Rejected applications, or ones still with the
Reporting Manager, cannot be opened (409). Stored in the employee's own `exist_form` document:
```
it_clearance: {approver_id, status: draft|submitted, created_at, submitted_at, submitted_by,
               items: [{key, particular, option: Yes|No, remarks, signature_file: {gridfs_file_id, filename, content_type, file_size, ...}}] x 4}
approval.it: {status: approved, approver_code, approver_name, approved_at}      approval.current_stage: "it" -> "hr"
```
Row keys: `laptop_system`, `software_id_card`, `email_deletion`, `hardware`. Every row needs Yes/No; a signature is optional per row but at least one is required.

The employee sees the stage as "IT Clearance" on their tracker, and (read-only) the completed clearance details once submitted. Juniors (e.g. JHS1474/JHS1551)
get no IT manager access: `/it/dashboard` and the clearance endpoints answer 403 for anyone who is not the IT manager of that employee.

| Method | Path |
|---|---|
| GET | `/api/exit-management/it/dashboard` |
| GET | `/api/exit-management/it/applications/{id}/clearance` (creates the draft on first open) |
| POST | `.../clearance/draft` `{ "items": [{ "key", "option", "remarks" }] }` |
| POST / GET / DELETE | `.../clearance/signature/{row_key}` (upload / view / remove one row's signature) |
| POST | `.../clearance/submit` |

Files: `backend/exit_management/it_clearance.py`, `static/exit_management/it.html` + `js/it.js` (dashboard), `it_form.html` + `js/it_form.js` (form),
IT Clearance tab (shown to IT managers only), `tests/test_exit_it_clearance.py`.

**IT managers are also Reporting Managers of their juniors.** JHS722 gets the Reporting Manager tabs (My Team Member Details, Employee Exit Applications) for JHS1474 / JHS1551
(`approvals.team_for` = people whose `ReportingEmpCode` is him + his IT juniors) with IT Clearance as an additional tab. He may approve their application and complete the handover
as Reporting Manager; IT Clearance only opens after that. The manager named in the employee's record (`ReportingEmpCode`, currently JHS1144 for both) can still act as before.

**Update - IT Clearance covers EVERY employee.** The IT manager (JHS722, `approvals.IT_MANAGER_TEAMS`) sees the submitted exit applications of all employees on the IT Clearance
dashboard (no Reporting Manager / team filter; drafts are never listed; his own form is excluded). Each row shows that employee's own Reporting Manager status
(Pending / Rejected / Approved - handover pending / Approved), handover status and IT Clearance status. The form can only be opened for filling when that employee's own
Reporting Manager has approved and the handover is submitted (otherwise 409); only the IT manager can complete the IT stage - owners and general IT approvers can no longer
approve it (they still approve HR). The "juniors" list now only makes JHS722 a Reporting Manager of JHS1474 / JHS1551 as well (see above).

The IT Clearance form uses the same signature logic as the handover form: choose ONE signature file in the "Upload a Signature" card, then tick "Add signature" on each row that carries it
(ticking uploads a copy for that row to GridFS, unticking removes it); rows left unticked stay unsigned, and at least one signed row is required to submit.

**IT approvers:** `approvals.IT_APPROVERS` = JHS722, JHS1474, JHS1551. Each sees the IT Clearance dashboard for every employee's submitted exit form and can open / fill / sign / approve / reject it
(only after that employee's own Reporting Manager approved and the handover was submitted; never for their own form). They share one clearance per employee: whoever submits first completes it
(`it_clearance.submitted_by`, `approval.it.approver_code`, timestamps); a second submit or reject answers 409. JHS1474 / JHS1551 have no Reporting Manager rights (JHS722 alone also acts as
Reporting Manager of them), so they see exactly two tabs: Employee Exit Form and IT Clearance.

**IT Clearance access collection - `it_clearance_approvers`.** Who may complete IT Clearance is now stored in this collection (one document per person), not in code:
```
{ "empid": "JHS722", "active": true }
```
Grant access: insert `{ "empid": "JHS123" }` in Compass. Revoke: set `"active": false` (or delete the document). The first time it is read while empty it is filled with JHS722, JHS1474 and JHS1551
(`repository.DEFAULT_IT_APPROVERS`); after that the collection alone decides. Everything else about IT Clearance (all employees' forms, locked until the Reporting Manager + handover, never their own form) is unchanged.
This replaces the `IT_APPROVERS` list in code; `exit_approvers` is still used for HR approvers and the JHS722 -> juniors Reporting Manager link.

**IT Clearance questions (replaced).** The old four questions are gone; the form now has exactly the 12 rows of "IT Assets, Access & Data Verification" (`it_clearance.ROWS`), each with Status Yes / No / NA (one per row),
Remarks and its own signature upload: `jhs_laptop`, `jhs_email_disabled`, `client_laptop`, `client_email_disabled`, `nexus_quant_id`, `msb_portal_id`, `work_data_handover`, `personal_email_removed`,
`mobile_sim`, `biometric_access`, `hardware_devices`, `other_it_assets`. Same `it_clearance` structure, GridFS storage and approval flow. An unsubmitted draft started with the old questions is reset to the new ones the next time
it is opened (its old signature files are removed); an already-submitted old form stays as it was. Submit needs a status on all 12 rows and at least one signature.

## HR Clearance (the HR stage, done by the HR manager JHS1423)

`backend/exit_management/hr_clearance.py`, pages `/exit-management/hr-clearance` (dashboard) and `/exit-management/hr-form?form=<id>`.
* **Who:** `approvals.HR_APPROVERS = ("JHS1423",)` plus HR rows of `exit_approvers` (`{stage: "hr", empid}`). The owners (JHS1191 / JHS1485) no longer approve the HR stage; the one-click `/approvals/{id}/approve` answers 409 for it.
  JHS1423 also has a team in `Employee_details`, so he sees four tabs: Employee Exit Form, My Team Member Details, Employee Exit Applications, HR Clearance (no IT Clearance tab). IT access of JHS722 / JHS1474 / JHS1551 is unchanged.
* **Flow:** Reporting Manager approved + handover submitted -> IT Clearance approved -> HR Clearance Pending. The dashboard lists every submitted form (any team, no drafts) with each stage's status; the form opens only on HR's turn (else 409) and never for the HR manager's own form.
* **Form:** three rows (Served Notice Period, Any Cash/Salary/Loan Adjustment Due?, ERP ID Deletion) with Yes/No, remarks and signature; the declaration text; Employee Signature (the one from the employee's Exit Form, viewable); HR Comments; HR Sign. Signatures use the one-file + tick-per-slot logic of the IT form, stored in GridFS (`kind: "hr_clearance"`).
* **Stored** in the employee's `exist_form` document: `hr_clearance: {approver_id, status, items[3], hr_comments, hr_signature_file, submitted_at, submitted_by}`; `approval.hr` gets status/approver/timestamps; Approve (submit) makes `approval.current_stage = "complete"` and Form Complete approved; Reject (comments required) sets `approval.hr.status = "rejected"` with `rejection_reason`.
* **API:** `GET /hr/dashboard`, `GET /hr/applications/{id}/clearance`, `POST .../clearance/draft`, `POST .../clearance/submit`, `POST /hr/applications/{id}/reject`, `POST|GET|DELETE .../clearance/signature/{notice_period|cash_adjustment|erp_deletion|hr_sign}` (+ `GET .../signature/employee`).

**HR approvers:** `approvals.HR_APPROVERS = ("JHS1423", "JHS911")`. JHS911 (HR Executive) has the same HR Clearance access as JHS1423 for every employee (never his own form) but no Reporting Manager rights, so he sees exactly two tabs: Employee Exit Form and HR Clearance.

**HR Clearance access collection - `hr_clearance_approvers`.** Who may complete HR Clearance is stored in this collection (same pattern as `it_clearance_approvers`), not in code:
```
{ "empid": "JHS1423", "active": true }
```
Grant: insert `{ "empid": "JHS123" }` in Compass. Revoke: set `"active": false` (or delete the document). The first time it is read while empty it is filled with JHS1423 and JHS911
(`repository.DEFAULT_HR_APPROVERS`); after that the collection alone decides. This replaces the `HR_APPROVERS` list in code and the HR rows of `exit_approvers` for HR Clearance.

**Reporting Manager dashboard - Action column.** Each filled exit form has two buttons: **Employee Exit Form** (read-only page `/exit-management/exit-form-view?form=<id>`, API `GET /manager/applications/{id}/exit-form` and `.../exit-form/signature`,
only for the employee's own Reporting Manager) and **Project Details** (the Project Related Details / handover form; the first click creates the draft through the existing approve endpoint, which starts the Reporting Manager stage).
The Approve / Reject buttons and the reject modal were removed from the page (the reject endpoint is still in the backend).

**Popups on the Reporting Manager dashboard.** The *Employee Exit Form* and *Project Details* buttons now open a popup on the same page (an iframe of `exit-form-view` / `handover` with `?embed=1`, which hides the navbar and back links). Submitting the Project Details form shows its success message
inside the popup and then closes it and refreshes the table (the page posts `{exitEmbed: "done"}` to the dashboard); nothing redirects.

**IT Clearance dashboard** now matches the Reporting Manager dashboard: no Approve / Reject buttons, an S.No column and an eye icon (all columns stacked vertically in a popup), and an *IT Clearance* button (or *View* once completed) that opens the IT Clearance form in a popup on the same page.
Submitting the form shows the success message inside the popup, then closes it and refreshes the list. The IT reject endpoint (`POST /it/applications/{id}/reject`) is still in the backend.

**Tabs without leaving the page (`js/tabs.js`).** On the Employee Exit Form, Tracker and Reporting Manager pages, the IT Clearance / HR Clearance / My Team Member Details tabs open in a frame under the tab bar (`?embed=tab`), so the address bar stays on the page the person opened (e.g. `/exit-management`).
Clicking the tab that was active on load brings the page's own content back. The standalone pages (`/exit-management/it-clearance` etc.) still work when opened directly.

**HR Clearance dashboard** now matches the IT one: no Approve / Reject buttons, S.No + eye icon columns (all columns stacked vertically in a popup), and an *HR Clearance* button (or *View* once completed) that opens the HR Clearance form in a popup on the same page; submitting closes the popup and refreshes the list.
The HR reject endpoint (`POST /hr/applications/{id}/reject`) is still in the backend.

**HR dashboard Action column** has three popup buttons: *Employee Exit Form* (read-only, what the employee filled in; `GET /hr/applications/{id}/exit-form` + `/exit-form/signature`), *IT Clearance* (the completed IT Clearance form, read-only, shown once IT is approved; `GET /hr/applications/{id}/it-clearance` + `/it-clearance/signature/{row}`)
and *HR Clearance* (fill / view the HR Clearance form). Only HR managers (`hr_clearance_approvers`) may use the HR read endpoints, never for their own form.

**HR dashboard - Project Details button.** After *Employee Exit Form*, HR sees *Project Details* (shown once the Reporting Manager stage is approved): the Reporting Manager's handover form, read-only, in a popup (`GET /hr/applications/{id}/handover` + `/handover/signature/{row}`; HR managers only, never for their own form).
Action order: Employee Exit Form, Project Details, IT Clearance, HR Clearance.

**Popups over the whole screen.** The Employee Exit Form / Project Details popups are light (white box, big title, coral Close button) and cover about 70% of the screen. When the Reporting Manager dashboard is shown inside a tab of another page
(`/exit-management`), the tab frame asks the top page to open the popup (`postMessage {exitPopup}`; handled in `js/tabs.js`) so it covers the real screen, not just the frame; closing it or submitting the form refreshes the tab frame (`{exitRefresh}`).
IT / HR Clearance popups inside a tab still open inside their frame.

**Same popup logic for the IT Clearance and HR Clearance tabs.** Their popups (Employee Exit Form, Project Details, IT Clearance, HR Clearance, and the small eye popup) now use the light style, and inside a tab frame the form popups are opened by the top page (`js/tabs.js`) so they cover ~70% of the screen.
The Close button is smaller and sits at the top right of every light popup.

**Export PDF.** When the whole exit process is complete (Form Complete approved) the tracker shows an *Export PDF* button. `GET /api/exit-management/export-pdf` (the signed-in employee's own form only; 404 if nothing submitted, 409 until complete)
returns `Employee_Exit_Form_<ID>.pdf` built by `backend/exit_management/pdf_export.py` (fpdf2 + Pillow, already in requirements): 1) Employee Exit Form, 2) Project Details, 3) IT Clearance, 4) HR Clearance, each on its own page(s).
Every signature is drawn as the actual image read back from GridFS (a PDF signature shows its first page), never a "view" link.

**A Yes needs a signature.** In the Project Details, IT Clearance and HR Clearance forms, every row answered **Yes** must carry a signature (tick "Add signature" after uploading). Submitting with an unsigned Yes row shows a "Signature required" popup listing those rows and the form is not submitted;
the server enforces the same rule (422 `'<row>': a signature is required when the answer is Yes`). No / NA rows need no signature; at least one signature is still required overall. The in-page popups (success / confirm / alert) were made more compact (max width 340px).

**E-mail notifications** (`backend/exit_management/notify.py`, Microsoft Graph with `TENANT_AP`, `CLIENT_AP`, `CLIENT_SECRET_AP`, `SENDER_AP` from `.env`; optional `APP_BASE_URL` adds an "Open Employee Exit Management" button; `EXIT_MAIL_DISABLED=1` turns sending off):
1. Employee submits the Exit Form -> the Reporting Manager (the one in `Employee_details`, plus the IT manager of IT-team juniors; HR representatives if there is no manager on record).
2. Reporting Manager submits Project Details -> every IT representative (`it_clearance_approvers`).
3. IT representative submits IT Clearance -> every HR representative (`hr_clearance_approvers`).
4. HR representative submits HR Clearance -> the employee: "Your exit process is completed".
Addresses come from the `EMail` field of `Employee_details`. Mails are sent in the background after the form is saved, one message per recipient; a missing address, missing setting or a Graph outage is logged and never affects the submission.

**PDF updates.** In the PDF the Signature column of Project Details, IT Clearance and HR Clearance now says "Signed" (the actual images are the signature boxes: Reporting Manager Signature, IT Representative Signature - added under the IT approval line - and, on the HR page, Employee Signature and **HR Signature**, formerly "HR Sign").
The HR Clearance form's "HR Sign" label is now "HR Signature". HR representatives get an *Export PDF* button after *HR Clearance* on completed applications (`GET /hr/applications/{id}/export-pdf`): the same PDF, one renderer (`pdf_export._render`), 403 for anyone who is not the HR representative of that employee, 409 until the exit process is complete.

**E-mail addresses and link.** Mails go only to the official address (`EMail` of `Employee_details`); `Personal EMail` is never used, and a person without an official address is skipped (logged). Every mail contains the login link https://jhstimesnap.in/ (text, link and a "Log in to JHS Timesnap" button; override with `EXIT_MAIL_LOGIN_URL`), including the final "Your exit process is completed" mail to the employee.

**Q23 reason.** If the employee answers **No** to Q23 ("Would you recommend the company...?") a "Please tell us why" box opens and is required (`exit_interview.recommend_reason`; server rule: `Please tell us why you would not recommend the company (Q23)`); the reason is cleared when the answer is Yes. It is shown to the Reporting Manager, on the approvals page and in the PDF (employee and HR copy are the same document).
A Reporting Manager who opens Employee Exit Management now stays on `/exit-management` (the one-time jump to `/exit-management/manager` was removed); the team and applications are one click away in the My Team Member Details tab.
