# backend/appraisal/questions.py
"""
Questions sourced EXACTLY from Revised_KRA_Excel_sheet.xlsx.
No questions added or removed beyond what the sheet specifies.

Sheet mapping (from HRMS_DATA Sheet1):
  'Sr.Audit Exec,Sr.Analyst'       → sr_audit_analyst
  'Audit Exec + MTs'               → audit_exec_mt
  'Article Assistant ,CMA Article' → article
  'Consultants, Sr.Consultant'     → consultant
  'Manager'                        → manager
  'PRINCIPAL & EXEC DIRECTOR'      → principal_exec_dir
  'ASSIC DIRECTOR'                 → assoc_director
  'HR Department'                  → hr  (3 sub-roles: TA Specialist, Payroll, Asst Mgr, HR Head)
  'Accounts Department'            → accounts (3 sub-roles: Sr Mgr, Exec, Accounts Exec)
  'IT Department'                  → it (2 sub-roles: IT Exec, Data Analyst)
  'Other Shared Service'           → shared_service (2 sub-roles: EA, BDE)
  'Sr.Service Quality Champion'    → sr_service_quality  (no designation mapped, kept for completeness)
  'TRADE FINANCE SPECILIST'        → trade_finance        (no designation mapped, kept for completeness)
  None                             → no_sheet  (Senior Partner, Director, Partner, etc.)

Weightage is stored internally for scoring but NEVER sent to the employee frontend.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# COMMON QUESTIONS  (Sheet: 'Common Questions', rows 3-13)
# Rows 3,5 have no question text — skipped (they are info-only: Emp ID, Reporting Partner)
# Row 6 (Department) and Row 8 (Month) are dropdowns with 0 points — kept as info fields
# ─────────────────────────────────────────────────────────────────────────────
COMMON_QUESTIONS: list[dict] = [
    # {
    #     "id": "C1",
    #     "section": "General",
    #     "question": "Name of the employee being evaluated",
    #     "type": "text",
    #     "weightage": 0,
    #     "required": False,
    #     "response_hint": "Short Answer",
    # },
    # {
    #     "id": "C2",
    #     "section": "General",
    #     "question": "Name of the reviewing manager",
    #     "type": "text",
    #     "weightage": 0,
    #     "required": False,
    #     "response_hint": "Short Answer",
    # },
    # {
    #     "id": "C3",
    #     "section": "General",
    #     "question": "Month of review",
    #     "type": "dropdown",
    #     "options": ["January","February","March","April","May","June",
    #                 "July","August","September","October","November","December"],
    #     "weightage": 0,
    #     "required": True,
    #     "response_hint": "Dropdown",
    # },
    {
        "id": "C4",
        "section": "Behaviour & Professionalism",
        "question": "Rate the grooming and professional behavior",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "C5",
        "section": "Behaviour & Professionalism",
        "question": "Rate punctuality",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "C6",
        "section": "Engagement & Learning",
        "question": "Please mention the number of \"Buddy Referrals\" shared by you during the year to JHS.",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Numeric (e.g., 0, 2, 5)",
    },
    {
        "id": "C7",
        "section": "Engagement & Learning",
        "question": "Have you attended any training organized by JHS Mumbai for you?",
        "type": "yes_no",
        "weightage": 10,
        "required": True,
        "response_hint": "Yes / No",
    },
    {
        "id": "C8",
        "section": "Engagement & Learning",
        "question": "Please mention the number of self-trainings or certifications taken and completed.",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Numeric (0 to 5)",
    },
    {
        "id": "C9",
        "section": "Engagement & Learning",
        "question": "Have you attended Excellencia session? If yes, enter the number of Excellencia series attended.",
        "type": "yes_no_number",
        "weightage": 0,
        "required": False,
        "response_hint": "Yes / No — if Yes, enter count",
    },
    {
        "id": "C10",
        "section": "Engagement & Learning",
        "question": "Have you attended Hall of Fame session? If yes, enter the number of Hall of Fame sessions attended.",
        "type": "yes_no_number",
        "weightage": 0,
        "required": False,
        "response_hint": "Yes / No — if Yes, enter count",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# ROLE-SPECIFIC QUESTIONS  —  keyed by category
# ─────────────────────────────────────────────────────────────────────────────

ROLE_QUESTIONS: dict[str, list[dict]] = {

    # ── Sheet: 'Sr.Audit Exec,Sr.Analyst' ────────────────────────────────────
    # Roles: Sr Audit Executive, Sr Analyst
    "sr_audit_analyst": [
        {
            "id": "SA1",
            "section": "Audit Performance",
            "question": "Number and type of audits or other assignments handled",
            "type": "textarea",
            "weightage": 20,
            "required": True,
            "response_hint": "Paragraph",
        },
        {
            "id": "SA2",
            "section": "Audit Performance",
            "question": "Please choose the number of frauds/critical observations identified across all the reports issued",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 20,
            "required": True,
            "response_hint": "Drop Down (1-25)",
        },
        {
            "id": "SA3",
            "section": "Audit Performance",
            "question": "Please mention the total number of controls tested across all reports issued during the month",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 10,
            "required": True,
            "response_hint": "Drop Down (1-25)",
        },
        {
            "id": "SA4",
            "section": "Team",
            "question": "Number of team members reporting to you for this month",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 10,
            "required": True,
            "response_hint": "Drop Down (1-25)",
        },
        {
            "id": "SA5",
            "section": "Engagement & Learning",
            "question": "Please mention the number of self-trainings or certifications taken and completed during the course of the month",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 10,
            "required": True,
            "response_hint": "Drop Down (1-25)",
        },
        {
            "id": "SA6",
            "section": "Knowledge Sharing",
            "question": "Have you presented any audit observations in the \"Hall of Fame\" presentation within this month?",
            "type": "yes_no",
            "weightage": 10,
            "required": True,
            "response_hint": "YES/NO",
        },
        {
            "id": "SA7",
            "section": "Process Compliance",
            "question": "Created checklist as per project scope and monitor it",
            "type": "yes_no",
            "weightage": 10,
            "required": True,
            "response_hint": "YES/NO",
        },
        {
            "id": "SA8",
            "section": "Client Relations",
            "question": "Was any feedback received from clients?",
            "type": "yes_no",
            "weightage": 10,
            "required": True,
            "response_hint": "YES/NO",
        },
    ],

    # ── Sheet: 'Audit Exec + MTs' ─────────────────────────────────────────────
    # Roles: Audit Executive, Management Trainee, Mangement & Audit Trainee, Analyst
    "audit_exec_mt": [
        {
            "id": "AE1",
            "section": "Audit Performance",
            "question": "Number and type of audits, or other assignments handled",
            "type": "textarea",
            "weightage": 20,
            "required": True,
            "response_hint": "Short Paragraph",
        },
        {
            "id": "AE2",
            "section": "Audit Performance",
            "question": "Please choose the number of frauds/critical observations identified across all the reports issued (0-25)",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 20,
            "required": True,
            "response_hint": "Drop Down (0-25)",
        },
        {
            "id": "AE3",
            "section": "Audit Performance",
            "question": "Please mention the total number of controls tested across all reports issued during the month (0-250)",
            "type": "number_dropdown",
            "options": list(range(0, 251)),
            "weightage": 20,
            "required": True,
            "response_hint": "Drop Down (0-250)",
        },
        {
            "id": "AE4",
            "section": "Client Relations",
            "question": "Please mention the total number of client complaints received for the last month",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 15,
            "required": True,
            "response_hint": "Drop Down (0-25)",
        },
        {
            "id": "AE5",
            "section": "Engagement & Learning",
            "question": "Please mention the number of self-trainings or certifications taken and completed during the course of the month (0-5)",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AE6",
            "section": "Knowledge Sharing",
            "question": "Have you presented any audit observations in the \"Hall of Fame\" presentation within this month? (Yes/No)",
            "type": "yes_no",
            "weightage": 10,
            "required": True,
            "response_hint": "YES/NO",
        },
        {
            "id": "AE7",
            "section": "Process Compliance",
            "question": "Did you follow audit checklists and suggest updates if needed?",
            "type": "yes_no",
            "weightage": 5,
            "required": True,
            "response_hint": "YES/NO",
        },
    ],

    # ── Sheet: 'Article Assistant ,CMA Article' ───────────────────────────────
    # Roles: Article, Article Assistant, Article Assistant-New, CMA Article
    "article": [
        {
            "id": "AR1",
            "section": "Audit Performance",
            "question": "Number and type of audits or other assignments handled",
            "type": "textarea",
            "weightage": 20,
            "required": True,
            "response_hint": "Short Paragraph",
        },
        {
            "id": "AR2",
            "section": "Audit Performance",
            "question": "Please choose the number of frauds/critical observations identified across all the reports issued",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 20,
            "required": True,
            "response_hint": "Drop Down (1-25)",
        },
        {
            "id": "AR3",
            "section": "Audit Performance",
            "question": "Please mention the total number of controls tested across all reports issued during the month",
            "type": "number_dropdown",
            "options": list(range(0, 251)),
            "weightage": 20,
            "required": True,
            "response_hint": "Drop Down (1-250)",
        },
        {
            "id": "AR4",
            "section": "Client Relations",
            "question": "Please mention the total number of client complaints received for the last month",
            "type": "number_dropdown",
            "options": list(range(0, 26)),
            "weightage": 20,
            "required": True,
            "response_hint": "Drop Down (1-25)",
        },
        {
            "id": "AR5",
            "section": "Engagement & Learning",
            "question": "Please mention the number of self-trainings or certifications taken and completed during the course of the month",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AR6",
            "section": "Knowledge Sharing",
            "question": "Have you presented any audit observations in the \"Hall of Fame\" presentation within this month?",
            "type": "yes_no",
            "weightage": 10,
            "required": True,
            "response_hint": "YES/NO",
        },
    ],

    # ── Sheet: 'Consultants, Sr.Consultant' ───────────────────────────────────
    # Roles: Consultant, Sr Consultant
    "consultant": [
        {
            "id": "CO1",
            "section": "Project Management",
            "question": "Timely project plan for all projects",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO2",
            "section": "Project Management",
            "question": "Weekly status updates",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO3",
            "section": "Project Management",
            "question": "Timely project report submission",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO4",
            "section": "Process & Quality",
            "question": "Checklist additions / updations",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO5",
            "section": "Process & Quality",
            "question": "Knowledge contribution and benchmarking with industry",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO6",
            "section": "Client Relations",
            "question": "Client feedback",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO7",
            "section": "Process & Quality",
            "question": "Scope coverage & regulatory compliance",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO8",
            "section": "Efficiency",
            "question": "Cost savings / process efficiency improvement",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO9",
            "section": "Business Development",
            "question": "Identification of business opportunities",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO10",
            "section": "Team",
            "question": "Number of new members added in your team in this month",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "CO11",
            "section": "Team",
            "question": "Count of resignations / absconsion in your team in this month",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Sheet: 'Manager' ──────────────────────────────────────────────────────
    # Roles: Manager, Sr Manager, Sr. Manager, (Assistant Manager goes to HR dept)
    "manager": [
        {
            "id": "MG1",
            "section": "Project Management",
            "question": "Project Planning — Did you create timely project plans for all assigned projects?",
            "type": "yes_no_example",
            "weightage": 15,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "MG2",
            "section": "Project Management",
            "question": "Weekly Updates — Did you consistently submit weekly status updates?",
            "type": "yes_no",
            "weightage": 15,
            "required": True,
            "response_hint": "Yes/No",
        },
        {
            "id": "MG3",
            "section": "Project Management",
            "question": "Report Submission — Were project reports submitted on time and as per standards?",
            "type": "yes_no",
            "weightage": 10,
            "required": True,
            "response_hint": "Yes/No",
        },
        {
            "id": "MG4",
            "section": "Process & Quality",
            "question": "Checklist Updates — Did you make any checklist updates or improvements?",
            "type": "yes_no_description",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No + Description",
        },
        {
            "id": "MG5",
            "section": "Knowledge Sharing",
            "question": "Knowledge Sharing — Did you share knowledge alerts or contribute to research/learning?",
            "type": "yes_no_details",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No + Details",
        },
        {
            "id": "MG6",
            "section": "Efficiency",
            "question": "Cost Efficiency — Were projects completed within the estimated cost (timesheet + standard cost)?",
            "type": "yes_no_justification",
            "weightage": 20,
            "required": True,
            "response_hint": "Yes/No + Brief Justification",
        },
        {
            "id": "MG7",
            "section": "Process & Quality",
            "question": "Industry Benchmarking — Did your work reflect benchmarking against global standards (e.g., COSO)?",
            "type": "yes_no_example",
            "weightage": 10,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "MG8",
            "section": "Client Relations",
            "question": "Client Feedback — Was the client feedback received positive and satisfactory?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "MG9",
            "section": "Process & Quality",
            "question": "Scope & Compliance Review — Was there complete coverage in terms of scope and compliance?",
            "type": "yes_no_notes",
            "weightage": 10,
            "required": True,
            "response_hint": "Yes/No + Notes if gaps exist",
        },
        {
            "id": "MG10",
            "section": "Business Development",
            "question": "Business Leads Generated — Did you identify any new business opportunities or leads?",
            "type": "yes_no_details",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No + Details",
        },
        {
            "id": "MG11",
            "section": "Business Development",
            "question": "Proposal Contribution — Did you contribute meaningfully to proposal submissions?",
            "type": "yes_no",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No",
        },
        {
            "id": "MG12",
            "section": "Engagement & Learning",
            "question": "Training Attended — Did you attend or conduct mandatory training sessions?",
            "type": "yes_no",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No",
        },
        {
            "id": "MG13",
            "section": "Team",
            "question": "Feedback from P&D — Was the feedback from P&D positive (e.g., no complaints, collaboration)?",
            "type": "yes_no_explanation",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No + Explanation",
        },
    ],

    # ── Sheet: 'PRINCIPAL & EXEC DIRECTOR' ───────────────────────────────────
    # Roles: Principle, Executive Director
    "principal_exec_dir": [
        {
            "id": "PE1",
            "section": "Project Management",
            "question": "Timely project plan for all projects",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE2",
            "section": "Project Management",
            "question": "Weekly status updates",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE3",
            "section": "Project Management",
            "question": "Timely project report submission",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE4",
            "section": "Process & Quality",
            "question": "Checklist additions / updations",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE5",
            "section": "Knowledge Sharing",
            "question": "Knowledge contribution and benchmarking with industry",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE6",
            "section": "Client Relations",
            "question": "Client feedback",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE7",
            "section": "Process & Quality",
            "question": "Scope coverage & regulatory compliance",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE8",
            "section": "Efficiency",
            "question": "Cost savings / process efficiency improvement",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE9",
            "section": "Business Development",
            "question": "Identification of business opportunities",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE10",
            "section": "Team",
            "question": "No. of new members added in your team in this month",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PE11",
            "section": "Team",
            "question": "Count of resignations / absconsion in your team in this month",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Sheet: 'ASSIC DIRECTOR' ───────────────────────────────────────────────
    # Roles: Associate Director
    "assoc_director": [
        {
            "id": "AD1",
            "section": "Strategic Planning",
            "question": "Strategic Planning & Execution — Did you effectively contribute to and execute the organization's strategic goals?",
            "type": "yes_no_example",
            "weightage": 20,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "AD2",
            "section": "Leadership",
            "question": "Leadership & Team Management — Did you lead, mentor, and manage teams effectively, ensuring alignment with organizational objectives?",
            "type": "yes_no_example",
            "weightage": 20,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "AD3",
            "section": "Collaboration",
            "question": "Cross-Functional Collaboration — Did you collaborate with other departments (e.g., operations, marketing, finance) to achieve organizational goals?",
            "type": "yes_no_example",
            "weightage": 15,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "AD4",
            "section": "Project Management",
            "question": "Project Management — Did you manage and oversee projects to ensure they were completed on time, within budget, and met expectations?",
            "type": "yes_no_example",
            "weightage": 15,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "AD5",
            "section": "Stakeholder Management",
            "question": "Stakeholder Engagement — Did you engage effectively with stakeholders, including senior management, clients, and external partners?",
            "type": "yes_no_example",
            "weightage": 10,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "AD6",
            "section": "Financial Oversight",
            "question": "Budgeting & Financial Oversight — Did you ensure the department's budget was managed effectively and align with financial goals?",
            "type": "yes_no_details",
            "weightage": 10,
            "required": True,
            "response_hint": "Yes/No + Details",
        },
        {
            "id": "AD7",
            "section": "Problem Solving",
            "question": "Problem-Solving & Decision-Making — Did you address and resolve challenges and make decisions that align with the company's best interests?",
            "type": "yes_no_example",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No + Example",
        },
        {
            "id": "AD8",
            "section": "Innovation",
            "question": "Process Improvement & Innovation — Did you identify and implement process improvements or innovative strategies to enhance efficiency or effectiveness?",
            "type": "yes_no_description",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No + Brief Description",
        },
        {
            "id": "AD9",
            "section": "Reporting",
            "question": "Performance Metrics & Reporting — Did you establish and monitor key performance indicators (KPIs) to track progress and report outcomes effectively?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AD10",
            "section": "Engagement & Learning",
            "question": "Professional Development & Learning — Did you engage in professional development activities and support team members in their growth?",
            "type": "yes_no_comments",
            "weightage": 5,
            "required": True,
            "response_hint": "Yes/No + Comments",
        },
    ],

    # ── Sheet: 'HR Department' ────────────────────────────────────────────────
    # Sub-roles within HR:
    #   Talent Acquisition Specialist → hr_ta
    #   Payroll Executive             → hr_payroll
    #   Assistant Manager (HR)        → hr_asst_mgr
    #   Sr HR Executive / HR Executive / HR Intern → hr_head (mapped to HR HEAD questions)

    # Talent Acquisition Specialist
    "hr_ta": [
        {
            "id": "TA1",
            "section": "Recruitment",
            "question": "Manage end-to-end recruitment lifecycle: sourcing, screening, interviewing, selection & offer rollout.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA2",
            "section": "Recruitment",
            "question": "Source candidates through job portals, LinkedIn, referrals, and campus drives.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA3",
            "section": "Coordination",
            "question": "Maintain timely coordination with hiring managers and interview panels.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA4",
            "section": "Reporting",
            "question": "Track, maintain, and update recruitment data, dashboards, and MIS reports.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA5",
            "section": "Reporting",
            "question": "Conduct weekly recruitment meetings with hiring partners and share weekly recruitment MIS.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA6",
            "section": "Process Compliance",
            "question": "Adherence to TAT (Turnaround Time) for each position from requisition to closure.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA7",
            "section": "Employer Branding",
            "question": "Contribute to employer branding activities on social platforms and through hiring campaigns.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA8",
            "section": "Innovation",
            "question": "Suggest recruitment process improvements or automation initiatives.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "TA9",
            "section": "Engagement & Learning",
            "question": "Attend training sessions relevant to recruitment tools, ATS, or HR tech.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # Payroll Executive
    "hr_payroll": [
        {
            "id": "PY1",
            "section": "Payroll Operations",
            "question": "Ensure accurate and timely processing of payroll for all employees.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY2",
            "section": "Payroll Operations",
            "question": "Maintain payroll records and ensure compliance with statutory and company policies.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY3",
            "section": "Coordination",
            "question": "Coordinate with HR and HRMIS for payroll inputs (attendance, deductions, etc.).",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY4",
            "section": "Employee Relations",
            "question": "Handle employee queries and grievances related to payroll and resolve promptly.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY5",
            "section": "Compliance",
            "question": "Ensure timely filing and payment of statutory dues (PF, ESI, TDS, etc.).",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY6",
            "section": "Payroll Operations",
            "question": "Ensure accurate and timely processing of OPE for all employees.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY7",
            "section": "Documentation",
            "question": "Prepare Appointment & Increment Letters for each employee.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY8",
            "section": "Engagement & Learning",
            "question": "Attend training on payroll software, statutory compliance, and updates.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY9",
            "section": "Coordination",
            "question": "Coordination with Sensys for coordination of HRMIS.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY10",
            "section": "Payroll Operations",
            "question": "Give salary slips to employees as and when need arises.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "PY11",
            "section": "Compliance",
            "question": "Ensure smooth NAPS/ NATS Contribution on monthly accurately and timely.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # Assistant Manager (HR)
    "hr_asst_mgr": [
        {
            "id": "AM1",
            "section": "HR Strategy",
            "question": "Drive and oversee the entire HR strategy, covering talent acquisition, employee engagement, and HR operations.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM2",
            "section": "Team Leadership",
            "question": "Lead and guide the Talent Acquisition team, ensuring alignment with business goals, TAT compliance, and quality hiring.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM3",
            "section": "Recruitment",
            "question": "Lead employer tie-ups for campus recruitments and strategic tie-ups.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM4",
            "section": "Reporting",
            "question": "Own and report on HR metrics, including headcount planning, attrition, cost-per-hire, and payroll costs.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM5",
            "section": "Reporting",
            "question": "Conduct monthly HR reviews with senior leadership; present people dashboards and strategic HR insights.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM6",
            "section": "Compliance",
            "question": "Ensure implementation and governance of HR policies, employee handbook, and legal compliance frameworks.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM7",
            "section": "Employer Branding",
            "question": "Lead employer branding initiatives and collaborate with communications for external and internal campaigns.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM8",
            "section": "Engagement & Learning",
            "question": "Attend training on HR Tech and other operations for HR.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AM9",
            "section": "Team Development",
            "question": "Provide coaching and development plans for the HR team; drive succession planning and internal mobility.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # Sr HR Executive / HR Executive / HR Intern → HR HEAD questions
    "hr_head": [
        {
            "id": "HH1",
            "section": "Recruitment",
            "question": "Lead end-to-end recruitment for articles, executives, and senior roles across the organization.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH2",
            "section": "Onboarding",
            "question": "Ensure smooth onboarding and induction processes for all new joiners, ensuring positive Day 1 experience.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH3",
            "section": "Performance Management",
            "question": "Design and implement performance review systems in alignment with JHS values and strategic goals.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH4",
            "section": "Employee Engagement",
            "question": "Drive continuous improvement initiatives to motivate employees, reduce attrition, and promote a positive work culture.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH5",
            "section": "Learning & Development",
            "question": "Identify training needs and organize technical, functional, and soft skills development programs.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH6",
            "section": "Reporting",
            "question": "Monitor and ensure accuracy of HR documentation, HRMS data, and prepare monthly HR MIS reports for leadership.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH7",
            "section": "Engagement & Learning",
            "question": "Attend training on HR Tech and other operations for HR.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH8",
            "section": "Team Leadership",
            "question": "Lead and support the Talent Acquisition team with hiring analytics, workforce planning, and employer branding.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH9",
            "section": "Compliance",
            "question": "Represent HR in management reviews, policy updates, and ensure compliance with labor laws and audits.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH10",
            "section": "HR Operations",
            "question": "Manage and organise HR Calendar for events, T&D for the team.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH11",
            "section": "HR Operations",
            "question": "Manage Gratuity and Insurance for the organisation.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH12",
            "section": "HR Operations",
            "question": "End to End Exit Interviews and Formalities for all employees.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH13",
            "section": "Compliance",
            "question": "Issue Show Cause and Warning letters to employees as and when required.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "HH14",
            "section": "Payroll",
            "question": "Ensure bonus calculations done timely and accurately.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Sheet: 'Accounts Department' ──────────────────────────────────────────
    # Sr Manager – Accounts
    "accounts_sr_mgr": [
        {
            "id": "AS1",
            "section": "Financial Leadership",
            "question": "Lead financial strategy, oversee accounting operations, and ensure compliance with financial regulations.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AS2",
            "section": "Reporting",
            "question": "Supervise monthly, quarterly, and annual closing of books and ensure accuracy in financial reporting.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AS3",
            "section": "Compliance",
            "question": "Timely filing of GST, TDS, PF, PT, and other statutory returns.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest) — also note the date",
        },
        {
            "id": "AS4",
            "section": "Team Management",
            "question": "Supervise account executive and Shared services team; review their work for accuracy and compliance.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AS5",
            "section": "Reporting",
            "question": "Review and finalize books of accounts, P&L, balance sheets, and financial reports for JHS.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AS6",
            "section": "Reporting",
            "question": "Ensure timely and accurate monthly/quarterly MIS reports to the Sr. partner.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AS7",
            "section": "Operations",
            "question": "Track service billing, vendor payments.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AS8",
            "section": "Attendance & Punctuality",
            "question": "Attendance record, punctuality in meeting deadlines, and task submissions.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AS9",
            "section": "Innovation",
            "question": "Drive automation and digitization of accounting processes.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # Executive – Accounts & Finance
    "accounts_exec_finance": [
        {
            "id": "AF1",
            "section": "Daily Operations",
            "question": "Prepare and maintain daily accounting records and vouchers.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF2",
            "section": "Reconciliation",
            "question": "Assist in bank reconciliations, ledger scrutiny, and journal entries.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF3",
            "section": "Reporting",
            "question": "Support month-end closing activities and reconciliation of books.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF4",
            "section": "Compliance",
            "question": "Ensure GST and TDS calculations and timely submission of returns.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF5",
            "section": "Operations",
            "question": "Coordinate with vendors and internal teams for invoice processing and payments.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF6",
            "section": "Operations",
            "question": "Maintain expense reports, petty cash, and tracking of advance settlements.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF7",
            "section": "Compliance",
            "question": "Generate UDIN timely and accurately.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF8",
            "section": "Cost Management",
            "question": "Participate in cost-saving initiatives and track routine operational expenses.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF9",
            "section": "Engagement & Learning",
            "question": "Attend training on accounting tools, ERP systems, and tax compliance.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AF10",
            "section": "Reporting",
            "question": "Makes Creditors and Debtors MIS weekly and sends to management.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # Accounts Executive / Sr Accountant / Junior Accountant
    "accounts_exec": [
        {
            "id": "AC1",
            "section": "Attendance & Punctuality",
            "question": "Attendance, punctuality, meeting deadlines, and task submissions.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AC2",
            "section": "Daily Operations",
            "question": "Timely and accurate recording of transactions in Tally, bank reconciliations, and data entry.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AC3",
            "section": "Reporting",
            "question": "Preparation of financial reports, MIS reports, and client-specific reports; review of ledgers.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AC4",
            "section": "Operations",
            "question": "Tracking invoices, vendor payments, collections, and client receivables.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AC5",
            "section": "Documentation",
            "question": "Filing of invoices, vouchers, bills, and statutory records; maintaining cash book.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AC6",
            "section": "Reconciliation",
            "question": "Reconcile employee reimbursements, travel bills, expense claims, and support internal audit.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AC7",
            "section": "Compliance",
            "question": "Timely filing of statutory returns (GST, TDS, etc.) and UDIN generation.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "AC8",
            "section": "Engagement & Learning",
            "question": "Assist in training sessions for accounting tools and tax updates.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Sheet: 'IT Department' ────────────────────────────────────────────────
    # Executive – IT (Shahnavaz & Ashar) — Sr IT Executive / IT Manager
    "it_exec": [
        {
            "id": "IT1",
            "section": "Technical Support",
            "question": "Provide technical support for hardware, software, and peripheral issues.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT2",
            "section": "Systems Management",
            "question": "Perform installation, configuration, and maintenance of IT systems.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT3",
            "section": "Networking",
            "question": "Monitor and troubleshoot LAN/WAN, internet connectivity, and network devices.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT4",
            "section": "Asset Management",
            "question": "Maintain asset inventory for hardware and software.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT5",
            "section": "Helpdesk",
            "question": "Respond to IT helpdesk tickets and resolve issues within agreed SLAs.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT6",
            "section": "Compliance",
            "question": "Assist in software license management and antivirus updates.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT7",
            "section": "Systems Management",
            "question": "Manage email servers, file sharing systems, and intranet services.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT8",
            "section": "Engagement & Learning",
            "question": "Participate in upskilling programs related to IT systems and cybersecurity.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT9",
            "section": "Data Management",
            "question": "Ensure proper data backup and recovery protocols.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT10",
            "section": "Networking",
            "question": "Manage and maintain network infrastructure, including servers, routers, firewalls.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "IT11",
            "section": "Security",
            "question": "Administer and secure user accounts, permissions, and group policies (AD, etc.).",
            "type": "rating",
            "weightage": 0,
            "required": False,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # Data Analyst / Data Scientist
    "it_data_analyst": [
        {
            "id": "DA1",
            "section": "Data Management",
            "question": "Collect, clean, and organize raw data from multiple sources.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA2",
            "section": "Reporting",
            "question": "Develop dashboards and reports using Excel, Power BI, or Tableau.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA3",
            "section": "Quality Assurance",
            "question": "Perform data validation and accuracy checks before publishing.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA4",
            "section": "Analytics",
            "question": "Conduct trend analysis, generate insights, and support decision-making.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA5",
            "section": "Collaboration",
            "question": "Collaborate with business teams to define data requirements.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA6",
            "section": "Automation",
            "question": "Maintain and update automated reporting systems.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA7",
            "section": "Collaboration",
            "question": "Work with IT/Admin teams on data access and integrity.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA8",
            "section": "Engagement & Learning",
            "question": "Stay updated on data tools, best practices, and industry standards.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "DA9",
            "section": "Documentation",
            "question": "Maintain documentation for data definitions, logic, and models.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Sheet: 'Other Shared Service' ─────────────────────────────────────────
    # Executive Assistant
    "ea": [
        {
            "id": "EA1",
            "section": "Scheduling & Coordination",
            "question": "Manage executive calendars, schedule meetings, and coordinate travel plans.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA2",
            "section": "Documentation",
            "question": "Prepare and review presentations, reports, and meeting minutes.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA3",
            "section": "Confidentiality",
            "question": "Handle confidential information with discretion and professionalism.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA4",
            "section": "Follow-ups",
            "question": "Ensure timely follow-ups and reminders for meetings and tasks.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA5",
            "section": "Stakeholder Liaison",
            "question": "Act as a liaison between senior management and internal/external stakeholders.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA6",
            "section": "Event Management",
            "question": "Organize and manage corporate events, meetings, and appointments.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA7",
            "section": "Communication",
            "question": "Support in drafting emails, communication, and documentation.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA8",
            "section": "Coordination",
            "question": "Arrange lead calls and huddle meet with the partners and directors.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "EA9",
            "section": "Priority Management",
            "question": "Stay aligned with executive priorities and manage tasks accordingly.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # Business Development Executive
    "bde": [
        {
            "id": "BD1",
            "section": "Business Development",
            "question": "Identify and pursue new business opportunities and potential clients.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "BD2",
            "section": "Research",
            "question": "Conduct market research and competitor analysis.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "BD3",
            "section": "Sales",
            "question": "Prepare and present sales proposals, decks, and business pitches.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "BD4",
            "section": "CRM",
            "question": "Maintain CRM systems, lead pipelines, and client interaction logs.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "BD5",
            "section": "Sales",
            "question": "Achieve assigned sales targets and KPIs.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "BD6",
            "section": "Client Relations",
            "question": "Attend client meetings, trade shows, or events to build business relations.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "BD7",
            "section": "Client Relations",
            "question": "Follow up on leads and ensure client satisfaction and retention.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "BD8",
            "section": "Market Intelligence",
            "question": "Stay updated on industry trends, products, and market shifts.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# DESIGNATION → CATEGORY MAP
# Sourced exactly from HRMS_DATA Sheet1 role→sheet mapping
# ─────────────────────────────────────────────────────────────────────────────
ROLE_CATEGORY_MAP: dict[str, str] = {
    # Sr.Audit Exec,Sr.Analyst
    "Sr Audit Executive":                       "sr_audit_analyst",
    "Sr Analyst":                               "sr_audit_analyst",

    # Audit Exec + MTs
    "Audit Executive":                          "audit_exec_mt",
    "Management Trainee":                       "audit_exec_mt",
    "Mangement & Audit Trainee":                "audit_exec_mt",
    "Analyst":                                  "audit_exec_mt",

    # Article Assistant ,CMA Article
    "Article":                                  "article",
    "Article Assistant":                        "article",
    "Article Assistant-New":                    "article",
    "CMA Article":                              "article",

    # Consultants, Sr.Consultant
    "Consultant":                               "consultant",
    "Sr Consultant":                            "consultant",

    # Manager
    "Manager":                                  "manager",
    "Sr Manager":                               "manager",
    "Sr. Manager":                              "manager",

    # PRINCIPAL & EXEC DIRECTOR
    "Principle":                                "principal_exec_dir",
    "Executive Director":                       "principal_exec_dir",

    # ASSIC DIRECTOR
    "Associate Director":                       "assoc_director",

    # HR Department — sub-role based
    "Talent Acquisition Specialist":            "hr_ta",
    "Payroll Executive":                        "hr_payroll",
    "Assistant Manager":                        "hr_asst_mgr",
    "Sr HR Executive":                          "hr_head",
    "HR Executive":                             "hr_head",
    "HR Intern":                                "hr_head",

    # Accounts Department — sub-role based
    "Sr Executive Accounts & Finance":          "accounts_exec_finance",
    "Accounts Executive":                       "accounts_exec",
    "Sr Accountant":                            "accounts_exec",
    "Junior Accountant":                        "accounts_exec",

    # IT Department — sub-role based
    "Sr IT Executive":                          "it_exec",
    "IT Manager":                               "it_exec",
    "Data Scientist":                           "it_data_analyst",
    "Cybersecurity Analyst":                    "it_exec",

    # Other Shared Service — sub-role based
    "Executive Assistant":                      "ea",
    "Business Development Executive":           "bde",

    # No sheet mapped — use shared_service fallback (not in Excel)
    # Senior Partner, Director, Partner, Associate Partner,
    # Office Assistant, System Auditor, Executive,
    # Executive - Knowledge & Special Projects
}

# Fallback for designations not in the map (no sheet in Excel)
DEFAULT_CATEGORY = None   # None means no role-specific questions


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def get_questions_for_designation(designation: str) -> dict:
    """
    Returns questions for the employee frontend — weightage stripped.
    {
      "category":  "audit_exec_mt",
      "common":    [...],
      "role":      [...],   # empty list if no sheet mapped
    }
    """
    category = ROLE_CATEGORY_MAP.get(designation, DEFAULT_CATEGORY)
    role_qs  = ROLE_QUESTIONS.get(category, []) if category else []

    def _strip(qs: list) -> list:
        exclude = {"weightage"}
        return [{k: v for k, v in q.items() if k not in exclude} for q in qs]

    return {
        "category": category or "none",
        "common":   _strip(COMMON_QUESTIONS),
        "role":     _strip(role_qs),
    }


def calculate_score(designation: str, answers: dict) -> dict:
    """
    Backend-only scoring. Never sent to employee.
    answers = { "C4": 4, "C5": 3, "AE1": "some text", ... }
    """
    category  = ROLE_CATEGORY_MAP.get(designation, DEFAULT_CATEGORY)
    role_qs   = ROLE_QUESTIONS.get(category, []) if category else []
    all_qs    = COMMON_QUESTIONS + role_qs

    total_weight = sum(q["weightage"] for q in all_qs)
    earned       = 0.0

    for q in all_qs:
        if q["weightage"] == 0:
            continue
        ans = answers.get(q["id"])
        if ans is None:
            continue

        qtype = q["type"]

        if qtype == "rating":
            try:
                earned += (float(ans) / 5.0) * q["weightage"]
            except (ValueError, TypeError):
                pass

        elif qtype == "number":
            # scale: assume 5 = max (capped)
            try:
                v = min(float(ans), 5.0)
                earned += (v / 5.0) * q["weightage"]
            except (ValueError, TypeError):
                pass

        elif qtype == "number_dropdown":
            # frauds/observations/controls — higher = better (capped at 25 or 250)
            try:
                max_val = max(q.get("options", [25])) or 25
                v = min(float(ans), max_val)
                earned += (v / max_val) * q["weightage"]
            except (ValueError, TypeError):
                pass

        elif qtype in ("yes_no", "yes_no_example", "yes_no_reason",
                       "yes_no_description", "yes_no_details",
                       "yes_no_justification", "yes_no_notes",
                       "yes_no_explanation", "yes_no_comments"):
            # "yes" → full points, "no" + reason → half points, empty → 0
            ans_lower = str(ans).strip().lower()
            if ans_lower.startswith("yes"):
                earned += q["weightage"]
            elif ans_lower.startswith("no"):
                earned += q["weightage"] * 0.5

        elif qtype in ("textarea", "text"):
            # non-empty → full points (manager reviews quality separately)
            if str(ans).strip():
                earned += q["weightage"]

        elif qtype == "dropdown":
            # info field — not scored
            pass

    percentage = round((earned / total_weight) * 100, 2) if total_weight else 0.0
    return {
        "score":      round(earned, 2),
        "max_score":  total_weight,
        "percentage": percentage,
    }