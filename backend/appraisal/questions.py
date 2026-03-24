# backend/appraisal/questions.py
"""
Question mapping — sourced exactly from KRA.xlsx (new file) plus
the Revised_KRA_Excel_sheet.xlsx for common questions.

Priority order when resolving questions for a logged-in employee:
  1. Employee-code match  → use that employee's specific questions
  2. Designation → Level 1 or Level 2 → use sheet '1' or sheet '2' questions
  3. Designation → role-specific category (from previous KRA sheet)
  4. Fallback → no role questions, common only

Weightage is STORED IN DB for analysis but NEVER sent to the employee UI.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# COMMON QUESTIONS  (same for every employee — from Common Questions sheet)
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
    #     "options": [
    #         "January", "February", "March", "April", "May", "June",
    #         "July", "August", "September", "October", "November", "December",
    #     ],
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
        "question": 'Please mention the number of "Buddy Referrals" shared by you during the year to JHS.',
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
# LEVEL 1 QUESTIONS  (Sheet: '1')
# Designations: Sr Manager, Sr Consultant, Consultant, Principle, Manager,
#               Executive Director, Assistant Manager, Sr Analyst, Sr. Manager
# 13 questions exactly as in sheet
# ─────────────────────────────────────────────────────────────────────────────
LEVEL_1_QUESTIONS: list[dict] = [
    {
        "id": "L1Q1",
        "section": "Project Delivery",
        "question": "I have worked on ____ number of projects in the assessment period.",
        "type": "text",
        "weightage": 15,
        "required": True,
        "response_hint": "Enter number and briefly describe the projects",
    },
    {
        "id": "L1Q2",
        "section": "Project Delivery",
        "question": "Total value of cost savings identified by me and my team",
        "type": "text",
        "weightage": 10,
        "required": True,
        "response_hint": "Mention amount (₹) or describe",
    },
    {
        "id": "L1Q3",
        "section": "Project Delivery",
        "question": "Timely project documentation completion and upload",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L1Q4",
        "section": "Project Delivery",
        "question": "Timely report submissions and updates",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L1Q5",
        "section": "Observations & Compliance",
        "question": "Number of observations which lead to regulatory non-compliance (e.g., Imprisonment, Fines & Penalties)",
        "type": "text",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter count",
    },
    {
        "id": "L1Q6",
        "section": "Observations & Compliance",
        "question": "I have personally identified ____ number of observations",
        "type": "text",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter number",
    },
    {
        "id": "L1Q7",
        "section": "Observations & Compliance",
        "question": "My team have identified ____ number of observations",
        "type": "text",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter number",
    },
    {
        "id": "L1Q8",
        "section": "Process & Quality",
        "question": "Number of audit checklists / RCMs updated",
        "type": "text",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter count",
    },
    {
        "id": "L1Q9",
        "section": "Client Relations",
        "question": "How many positive client feedbacks received for you or your team?",
        "type": "text",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter count",
    },
    {
        "id": "L1Q10",
        "section": "Client Relations",
        "question": "How many negative client feedbacks / escalations received for you or your team?",
        "type": "text",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter count",
    },
    {
        "id": "L1Q11",
        "section": "Team",
        "question": "Attrition Percentage",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L1Q12",
        "section": "Process & Quality",
        "question": "Quality Missouts",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L1Q13",
        "section": "Project Delivery",
        "question": "Project Plans",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL 2 QUESTIONS  (Sheet: '2')
# Designations: Sr Audit Executive, Mangement & Audit Trainee, Management Trainee,
#               Article, Audit Executive, Analyst, Article Assistant,
#               Article Assistant-New, System Auditor, CMA Article
# 9 questions exactly as in sheet
# ─────────────────────────────────────────────────────────────────────────────
LEVEL_2_QUESTIONS: list[dict] = [
    {
        "id": "L2Q1",
        "section": "Project Delivery",
        "question": "I have worked on ____ number of projects in the assessment period.",
        "type": "text",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter number and briefly describe the projects",
    },
    {
        "id": "L2Q2",
        "section": "Project Delivery",
        "question": "Timely project documentation completion and upload",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L2Q3",
        "section": "Project Delivery",
        "question": "Timely status updates",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L2Q4",
        "section": "Observations & Compliance",
        "question": "Number of observations which lead to regulatory non-compliance (e.g., Imprisonment, Fines & Penalties)",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L2Q5",
        "section": "Observations & Compliance",
        "question": "I have personally identified ____ number of observations",
        "type": "text",
        "weightage": 15,
        "required": True,
        "response_hint": "Enter number",
    },
    {
        "id": "L2Q6",
        "section": "Observations & Compliance",
        "question": "Please mention the total number of controls tested / audit checkpoints tested across all reports issued during the period annually",
        "type": "text",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter count",
    },
    {
        "id": "L2Q7",
        "section": "Process & Quality",
        "question": "Quality Missouts",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L2Q8",
        "section": "Project Delivery",
        "question": "Completion of project plans",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "L2Q9",
        "section": "Project Delivery",
        "question": "Delays",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEE-CODE-SPECIFIC QUESTIONS
# Key = employee code (uppercase), Value = list of question dicts
# ─────────────────────────────────────────────────────────────────────────────
EMP_CODE_QUESTIONS: dict[str, list[dict]] = {

    # ── IT Department — JHS722 (Sr IT Executive) — 8 questions ──────────────
    "JHS722": [
        {
            "id": "E_722_1",
            "section": "Technical Support",
            "question": "Handle escalated issues from L1.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_722_2",
            "section": "System Administration",
            "question": "Manage servers, OS, patching, and performance.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_722_3",
            "section": "Network Management",
            "question": "Monitor and troubleshoot LAN/WAN, firewall, and routing.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_722_4",
            "section": "Email & Server Management",
            "question": "Administer email servers and file systems.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_722_5",
            "section": "Backup & Recovery",
            "question": "Ensure backup jobs run successfully and perform recovery testing.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_722_6",
            "section": "Security Management",
            "question": "Manage AD, permissions, policies, and endpoint security.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_722_7",
            "section": "License Management",
            "question": "Ensure software compliance and timely renewals.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_722_8",
            "section": "Documentation",
            "question": "Maintain SOPs and technical documentation.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── IT Department — JHS1361 — 7 questions ────────────────────────────────
    "JHS1361": [
        {
            "id": "E_1361_1",
            "section": "Technical Support",
            "question": "Provide first-level support for hardware, software, and peripherals.",
            "type": "rating",
            "weightage": 25,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1361_2",
            "section": "Ticket Handling",
            "question": "Log, track, and resolve IT tickets within SLA.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1361_3",
            "section": "System Setup",
            "question": "Install and configure desktops, laptops, and printers.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1361_4",
            "section": "Basic Network Troubleshooting",
            "question": "Resolve LAN/WiFi and basic connectivity issues.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1361_5",
            "section": "Asset Management",
            "question": "Maintain IT asset inventory and records.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1361_6",
            "section": "User Support",
            "question": "Assist users with email, login, and software issues.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1361_7",
            "section": "Antivirus & Updates",
            "question": "Ensure endpoints are updated and protected.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Automation Team — JHS1191 (Data Scientist) — 9 questions ─────────────
    "JHS1191": [
        {
            "id": "E_1191_1",
            "section": "Data Discovery",
            "question": "Was the Data Discovery function established effectively (team setup, workflow, project initiation within timelines)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_2",
            "section": "Dashboards",
            "question": "Were dashboards developed/migrated (Power BI or others) as per targets with minimal downtime (<2 days)?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_3",
            "section": "Dashboards",
            "question": "Were dashboards user-friendly and did they achieve ≥80% stakeholder satisfaction?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_4",
            "section": "Automation",
            "question": "Were automation initiatives delivered effectively with measurable impact (e.g., ≥1000 hours saved/year)?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_5",
            "section": "Audit Innovation",
            "question": "Were audit innovation initiatives (sampling tools/methods) successfully implemented and adopted?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_6",
            "section": "Collaboration",
            "question": "Was collaboration with HIU/HR/efficiency teams effective in delivering strategic projects?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_7",
            "section": "Application Projects",
            "question": "Were application projects executed smoothly (low bugs, timely fixes, performance improvements, client onboarding)?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_8",
            "section": "Code Management",
            "question": "Was code management handled properly (version control, backups, zero data loss, ≥95% compliance)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1191_9",
            "section": "Professional Conduct",
            "question": "Were training, knowledge sharing, and professional conduct maintained as per expectations?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Automation Team — JHS1283 — 9 questions ───────────────────────────────
    "JHS1283": [
        {
            "id": "E_1283_1",
            "section": "Delivery",
            "question": "Were features delivered on time as per sprint/project timelines (≥90% adherence)?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_2",
            "section": "Frontend",
            "question": "Was the frontend (HTML/CSS/JS/React) implemented with responsive design and minimal UI bugs?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_3",
            "section": "Backend",
            "question": "Were backend APIs (FastAPI) developed efficiently with proper structure, validation, and performance?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_4",
            "section": "Database",
            "question": "Was database design (MongoDB) optimized for performance, scalability, and correct data handling?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_5",
            "section": "Code Quality",
            "question": "Was code quality maintained (readability, modularity, reusability, minimal rework)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_6",
            "section": "Version Control",
            "question": "Were version control practices (Git/GitHub) properly followed (clean commits, branching, PRs)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_7",
            "section": "Deployment",
            "question": "Was application deployment handled successfully with minimal downtime/issues?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_8",
            "section": "Bug Resolution",
            "question": "Were bugs/issues resolved within defined timelines with proper root cause fixes?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1283_9",
            "section": "Documentation",
            "question": "Was documentation (API docs, setup guides) created and maintained properly?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Other Shared Services — JHS963 (BDE) — 10 questions ──────────────────
    "JHS963": [
        {
            "id": "E_963_1",
            "section": "Marketing & Campaigns",
            "question": "Were marketing campaigns executed on time and did they achieve defined engagement targets?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_2",
            "section": "Customer Acquisition",
            "question": "How effectively were qualified leads generated and converted into business opportunities?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_3",
            "section": "Knowledge Series",
            "question": "Were webinars/events conducted consistently with strong participation and business outcomes?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_4",
            "section": "Content & Digital Presence",
            "question": "Was content (posts/videos) published regularly and aligned with branding and engagement goals?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_5",
            "section": "Marketing Communication",
            "question": "Were email/WhatsApp campaigns executed on time with good response rates?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_6",
            "section": "CRM & Database Management",
            "question": "Was the CRM database updated accurately with relevant and usable contact data?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_7",
            "section": "Proposals & Tenders",
            "question": "Were proposals and submissions completed on time with high quality and minimal rework?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_8",
            "section": "Client Engagement",
            "question": "Were client engagement activities executed and feedback effectively captured?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_9",
            "section": "Internal Coordination",
            "question": "Was coordination with internal teams smooth with timely delivery of tasks?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_963_10",
            "section": "Performance Tracking",
            "question": "Were performance reports submitted regularly with actionable improvements identified?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Other Shared Services — JHS1176 (BDE) — 10 questions ─────────────────
    "JHS1176": [
        {
            "id": "E_1176_1",
            "section": "Marketing & Campaigns",
            "question": "Were marketing campaigns executed consistently and did they achieve defined engagement targets?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_2",
            "section": "Customer Acquisition",
            "question": "How effectively were qualified leads generated and converted into business opportunities?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_3",
            "section": "Knowledge Series",
            "question": "Were knowledge sessions/webinars conducted regularly with strong participation and business outcomes?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_4",
            "section": "Content & Digital Presence",
            "question": "Was content (LinkedIn, YouTube, creatives) published consistently and aligned with brand positioning?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_5",
            "section": "Marketing Communication",
            "question": "Were marketing communications (email/WhatsApp) executed on time with measurable response rates?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_6",
            "section": "CRM & Database Management",
            "question": "Was the CRM/database accurately maintained with regular updates and relevant decision-maker data?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_7",
            "section": "Proposals & Tenders",
            "question": "Were proposals, empanelments, and tenders completed on time with high quality?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_8",
            "section": "Client Engagement",
            "question": "Were client engagement activities executed effectively and feedback captured?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_9",
            "section": "Internal Coordination",
            "question": "Was internal coordination smooth with timely execution of tasks and deliverables?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1176_10",
            "section": "Performance Tracking",
            "question": "Were performance reports submitted regularly with actionable insights and improvements?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Other Shared Services — JHS1303 (Knowledge & Special Projects) — 10 Qs
    "JHS1303": [
        {
            "id": "E_1303_1",
            "section": "Knowledge Repository",
            "question": "Was the knowledge repository maintained with ≥95% accuracy and updated regularly?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_2",
            "section": "Content Delivery",
            "question": "Were daily articles and monthly newsletters delivered consistently and on time?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_3",
            "section": "Regulatory Updates",
            "question": "Were regulatory updates tracked and incorporated within defined timelines (≤48 hours)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_4",
            "section": "Knowledge Sessions",
            "question": "Were knowledge sessions conducted effectively with good participation and feedback (≥4 rating)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_5",
            "section": "Content Quality",
            "question": "Was content quality maintained with strong peer review scores (≥4/5)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_6",
            "section": "Repository Usage",
            "question": "Was repository usage improved (e.g., ≥15% growth in engagement/usage)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_7",
            "section": "Quality Standards",
            "question": "Were quality standards (version control, audits, archiving) consistently followed?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_8",
            "section": "Special Projects",
            "question": "Were special projects completed on time with proper coordination and reporting?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_9",
            "section": "Compliance",
            "question": "Was compliance maintained with zero delays in updates and adherence to standards?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1303_10",
            "section": "Professional Conduct",
            "question": "Was professional conduct maintained with no complaints and strong workplace behavior?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Other Shared Services — JHS911 (Executive Assistant) — 8 questions ───
    "JHS911": [
        {
            "id": "E_911_1",
            "section": "Calendar & Scheduling",
            "question": "Was the Founder's calendar managed accurately with no overlaps and proactive planning (daily/weekly alignment, minimal reschedules)?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_911_2",
            "section": "Communication",
            "question": "Was communication handled professionally with timely responses (≤24 hrs), strong follow-ups (≥95%), and zero escalations?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_911_3",
            "section": "Meeting Management",
            "question": "Were meetings managed effectively with agendas shared in advance, MOMs circulated within 24 hours, and accurate documentation (≥98%)?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_911_4",
            "section": "Strategic Support",
            "question": "Was strategic and administrative support delivered efficiently (travel, approvals, tasks ≥95% on time, proactive risk identification)?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_911_5",
            "section": "Recruitment Coordination",
            "question": "Was recruitment coordination handled efficiently with timely interview scheduling (≤48 hrs) and no scheduling errors?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_911_6",
            "section": "Offer & Joining",
            "question": "Was offer rollout and joining coordination completed on time with proper follow-ups and proactive dropout risk handling?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_911_7",
            "section": "Recruitment Tracking",
            "question": "Was recruitment tracking maintained accurately with real-time updates and zero data gaps?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_911_8",
            "section": "Operational Independence",
            "question": "Did the role contribute to reducing the Founder's operational dependency through proactive execution and ownership?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Accounts — JHS48 (Sr Executive Accounts & Finance) — 10 questions ────
    "JHS48": [
        {
            "id": "E_48_1",
            "section": "Financial Leadership",
            "question": "Lead financial strategy, oversee accounting operations, and ensure compliance with financial regulations.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_2",
            "section": "Reporting",
            "question": "Supervise monthly, quarterly, and annual closing of books and ensure accuracy in financial reporting for Andheri.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_3",
            "section": "Compliance",
            "question": "Timely filing of GST, TDS, PF, PT, and other statutory returns.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_4",
            "section": "Team Management",
            "question": "Supervise account executive and Shared services team; review their work for accuracy and compliance.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_5",
            "section": "Reporting",
            "question": "Review and finalize books of accounts, P&L, balance sheets, and financial reports for JHS.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_6",
            "section": "Reporting",
            "question": "Ensure timely and accurate monthly/quarterly MIS reports to the Sr. partner.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_7",
            "section": "Operations",
            "question": "Track service billing and vendor payments.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_8",
            "section": "Innovation",
            "question": "Drive automation and digitization of accounting processes.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_9",
            "section": "Budgeting",
            "question": "Budget vs Actual tracking and variance analysis.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_48_10",
            "section": "Compliance",
            "question": "Consolidated Compliance Tracker — maintained accurately and submitted on time.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── Accounts — JHS266 — 8 questions ──────────────────────────────────────
    "JHS266": [
        {
            "id": "E_266_1",
            "section": "Daily Operations",
            "question": "Prepare and maintain daily accounting records and vouchers.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_266_2",
            "section": "Reconciliation",
            "question": "Assist in bank reconciliations, ledger scrutiny, and journal entries.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_266_3",
            "section": "Month-End",
            "question": "Support month-end closing activities and reconciliation of books.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_266_4",
            "section": "Billing",
            "question": "Monthly Billing & Invoice raising to clients.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_266_5",
            "section": "Operations",
            "question": "Maintain expense reports and petty cash.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_266_6",
            "section": "Compliance",
            "question": "Generate UDIN timely and accurately.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_266_7",
            "section": "Cost Management",
            "question": "Participate in cost-saving initiatives and track routine operational expenses.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_266_8",
            "section": "Reporting",
            "question": "Makes Debtors MIS weekly and sends to management.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],

    # ── HR Department — JHS1423 (Talent Acquisition Specialist) — 8 questions ─
    "JHS1423": [
        {
            "id": "E_1423_1",
            "section": "Recruitment",
            "question": "Manage end-to-end recruitment lifecycle: sourcing, screening, interviewing, selection & salary confirmations.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1423_2",
            "section": "Coordination",
            "question": "Maintain timely coordination with hiring managers and interview panels.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1423_3",
            "section": "Reporting",
            "question": "Track, maintain, and update recruitment data, dashboards, and MIS reports.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1423_4",
            "section": "Meetings",
            "question": "Conduct weekly recruitment meetings and MOM with hiring partners and share weekly recruitment MIS.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1423_5",
            "section": "TAT Compliance",
            "question": "Adherence to TAT (Turnaround Time) for each position from requisition to closure (45 days max).",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1423_6",
            "section": "Employer Branding",
            "question": "Contribute to employer branding activities on social platforms and through hiring campaigns.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1423_7",
            "section": "Process Improvement",
            "question": "Suggest recruitment process improvements or automation initiatives.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_1423_8",
            "section": "Recruitment Volume",
            "question": "Number of recruitments done in a quarter.",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter count",
        },
    ],

    # ── HR Department — JHS729 (Payroll Executive) — 10 questions ────────────
    "JHS729": [
        {
            "id": "E_729_1",
            "section": "Payroll Processing",
            "question": "Ensure accurate and timely processing of payroll for all employees.",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_2",
            "section": "Compliance",
            "question": "Maintain payroll records and ensure compliance with statutory and company policies.",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_3",
            "section": "Coordination",
            "question": "Coordinate with HR and HRMS for payroll inputs (attendance, deductions, etc.).",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_4",
            "section": "Employee Relations",
            "question": "Handle employee queries and grievances related to payroll and resolve promptly.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_5",
            "section": "FNF Processing",
            "question": "Ensure accurate and timely processing of FNF.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_6",
            "section": "OPE Processing",
            "question": "Ensure accurate and timely processing of OPE for all employees.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_7",
            "section": "Documentation",
            "question": "Prepare Appointment & Increment Letters for each employee.",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_8",
            "section": "SSP Portal",
            "question": "Ensure timely and accurate updation on SSP portal (Articles & CAs).",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_9",
            "section": "Salary Slips",
            "question": "Give salary slips/consultant invoices to employees as and when need arises.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
        {
            "id": "E_729_10",
            "section": "NAPS/NATS",
            "question": "Ensure smooth NAPS/NATS contribution on monthly basis accurately and timely.",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
        },
    ],
}

# ── Cybersecurity Analyst — role-based (designation match) — 9 questions ─────
# Applies to designation "Cybersecurity Analyst" if no emp-code match
CYBERSECURITY_QUESTIONS: list[dict] = [
    {
        "id": "CY1",
        "section": "VA/PT Assessments",
        "question": "Were VA/PT assessments completed as per plan with ≥95% accuracy in findings?",
        "type": "rating",
        "weightage": 20,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY2",
        "section": "ITGC Reviews",
        "question": "Were ITGC reviews completed fully with reduction in control gaps?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY3",
        "section": "Cybersecurity Audits",
        "question": "Were cybersecurity audits conducted with ≥95% compliance and no major issues?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY4",
        "section": "SOC Reports",
        "question": "Were SOC1/SOC2 reports delivered on time with ≥90% client satisfaction?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY5",
        "section": "Reporting",
        "question": "Was reporting/documentation accurate with zero rework?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY6",
        "section": "Audit Closure",
        "question": "Were audit observations closed within timelines?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY7",
        "section": "Process Improvement",
        "question": "Did you contribute to process improvements or methodology enhancements?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY8",
        "section": "Upskilling",
        "question": "Were upskilling/certifications completed as required?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
    {
        "id": "CY9",
        "section": "Coordination",
        "question": "Was coordination with clients and teams smooth and timely?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 0 (lowest) to 5 (highest)",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# DESIGNATION → LEVEL MAP  (from Sheet1 of KRA.xlsx)
# ─────────────────────────────────────────────────────────────────────────────
DESIGNATION_LEVEL_MAP: dict[str, int] = {
    # Level 1
    "Sr Manager":          1,
    "Sr Consultant":       1,
    "Consultant":          1,
    "Principle":           1,
    "Manager":             1,
    "Executive Director":  1,
    "Assistant Manager":   1,
    "Sr Analyst":          1,
    "Sr. Manager":         1,
    # Level 2
    "Sr Audit Executive":          2,
    "Mangement & Audit Trainee":   2,
    "Management Trainee":          2,
    "Article":                     2,
    "Audit Executive":             2,
    "Analyst":                     2,
    "Article Assistant":           2,
    "Article Assistant-New":       2,
    "System Auditor":              2,
    "CMA Article":                 2,
}

# Designations that use Cybersecurity role questions (no emp-code)
CYBERSECURITY_DESIGNATIONS: set[str] = {"Cybersecurity Analyst"}

# Designations with no questions yet (Sheet1 'No')
NO_QUESTIONS_DESIGNATIONS: set[str] = {
    "Accounts Executive", "Sr Accountant", "Junior Accountant",
    "IT Manager", "Talent Acquisition Specialist", "HR Executive", "HR Intern",
}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def _strip_weightage(qs: list[dict]) -> list[dict]:
    """Remove weightage before sending to employee UI."""
    exclude = {"weightage"}
    return [{k: v for k, v in q.items() if k not in exclude} for q in qs]


def get_questions_for_employee(emp_id: str, designation: str) -> dict:
    """
    Priority:
      1. Employee-code match → emp-code-specific questions
      2. Designation → Level 1 or Level 2 questions
      3. Designation → Cybersecurity Analyst
      4. No role questions

    Returns:
      {
        "source":    "emp_code" | "level_1" | "level_2" | "cybersecurity" | "none",
        "category":  str,
        "common":    [...],    # weightage stripped
        "role":      [...],    # weightage stripped
      }
    """
    emp_upper = (emp_id or "").strip().upper()

    # 1. Employee-code match
    if emp_upper in EMP_CODE_QUESTIONS:
        return {
            "source":   "emp_code",
            "category": f"emp_{emp_upper}",
            "common":   _strip_weightage(COMMON_QUESTIONS),
            "role":     _strip_weightage(EMP_CODE_QUESTIONS[emp_upper]),
        }

    # 2. Level-based
    level = DESIGNATION_LEVEL_MAP.get(designation)
    if level == 1:
        return {
            "source":   "level_1",
            "category": "level_1",
            "common":   _strip_weightage(COMMON_QUESTIONS),
            "role":     _strip_weightage(LEVEL_1_QUESTIONS),
        }
    if level == 2:
        return {
            "source":   "level_2",
            "category": "level_2",
            "common":   _strip_weightage(COMMON_QUESTIONS),
            "role":     _strip_weightage(LEVEL_2_QUESTIONS),
        }

    # 3. Cybersecurity Analyst
    if designation in CYBERSECURITY_DESIGNATIONS:
        return {
            "source":   "cybersecurity",
            "category": "cybersecurity",
            "common":   _strip_weightage(COMMON_QUESTIONS),
            "role":     _strip_weightage(CYBERSECURITY_QUESTIONS),
        }

    # 4. No role questions
    return {
        "source":   "none",
        "category": "none",
        "common":   _strip_weightage(COMMON_QUESTIONS),
        "role":     [],
    }


def calculate_score(emp_id: str, designation: str, answers: dict) -> dict:
    """
    Backend-only scoring — never returned to employee UI.
    answers = { "C4": 4, "L1Q1": "text...", "E_1191_1": 5, ... }
    """
    emp_upper = (emp_id or "").strip().upper()

    # Resolve role questions (with weightage)
    if emp_upper in EMP_CODE_QUESTIONS:
        role_qs = EMP_CODE_QUESTIONS[emp_upper]
    elif DESIGNATION_LEVEL_MAP.get(designation) == 1:
        role_qs = LEVEL_1_QUESTIONS
    elif DESIGNATION_LEVEL_MAP.get(designation) == 2:
        role_qs = LEVEL_2_QUESTIONS
    elif designation in CYBERSECURITY_DESIGNATIONS:
        role_qs = CYBERSECURITY_QUESTIONS
    else:
        role_qs = []

    all_qs = COMMON_QUESTIONS + role_qs
    total_weight = sum(q["weightage"] for q in all_qs)
    earned = 0.0

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
            try:
                v = min(float(ans), 5.0)
                earned += (v / 5.0) * q["weightage"]
            except (ValueError, TypeError):
                pass

        elif qtype in ("text", "textarea"):
            if str(ans).strip():
                earned += q["weightage"]

        elif qtype in ("yes_no", "yes_no_number"):
            if str(ans).strip().lower().startswith("yes"):
                earned += q["weightage"]
            elif str(ans).strip().lower().startswith("no"):
                earned += q["weightage"] * 0.5

        elif qtype == "dropdown":
            if str(ans).strip():
                earned += q["weightage"]

    percentage = round((earned / total_weight) * 100, 2) if total_weight else 0.0
    return {
        "score":      round(earned, 2),
        "max_score":  total_weight,
        "percentage": percentage,
        "source":     "emp_code" if emp_upper in EMP_CODE_QUESTIONS
                      else f"level_{DESIGNATION_LEVEL_MAP.get(designation, 'none')}",
    }