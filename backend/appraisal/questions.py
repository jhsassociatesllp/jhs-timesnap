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
        "question": "How would you rate yourself on grooming and professional behavior?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "C5",
        "section": "Behaviour & Professionalism",
        "question": "How would you rate yourself on punctuality?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "C6",
        "section": "Engagement & Learning",
        "question": "How many Buddy Referrals have you shared with JHS during this year?",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 2, 5)",
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
        "question": "How many self-trainings or certifications have you completed during this period?",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 1, 2)",
    },
    {
        "id": "C9",
        "section": "Engagement & Learning",
        "question": "Have you attended any Excellencia session? If yes, how many sessions did you attend?",
        "type": "yes_no_number",
        "weightage": 0,
        "required": False,
        "response_hint": "Select Yes or No — if Yes, enter the count",
    },
    {
        "id": "C10",
        "section": "Engagement & Learning",
        "question": "Have you presented at any Hall of Fame session? If yes, how many sessions did you present?",
        "type": "yes_no_number",
        "weightage": 0,
        "required": False,
        "response_hint": "Select Yes or No — if Yes, enter the count",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL 1 QUESTIONS  (Sheet: '1')
# Designations: Sr Manager, Sr Consultant, Consultant, Principle, Manager,
#               Executive Director, Assistant Manager, Sr Analyst, Sr. Manager
# ─────────────────────────────────────────────────────────────────────────────
LEVEL_1_QUESTIONS: list[dict] = [
    {
        "id": "L1Q1",
        "section": "Project Delivery",
        "question": "How many projects have you worked on during this assessment period?",
        "type": "number",
        "weightage": 15,
        "required": True,
        "response_hint": "Enter the number of projects and a brief description of each",
    },
    {
        "id": "L1Q2",
        "section": "Project Delivery",
        "question": "What is the total value of cost savings identified by you and your team?",
        "type": "text",
        "weightage": 10,
        "required": True,
        "response_hint": "Mention the amount in ₹ or provide a brief description",
    },
    {
        "id": "L1Q3",
        "section": "Project Delivery",
        "question": "How would you rate yourself on timely completion and upload of project documentation?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L1Q4",
        "section": "Project Delivery",
        "question": "How would you rate yourself on timely report submissions and updates?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L1Q5",
        "section": "Observations & Compliance",
        "question": "How many observations led to regulatory non-compliance (e.g., Imprisonment, Fines & Penalties) during this period?",
        "type": "number",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 1, 2)",
    },
    {
        "id": "L1Q6",
        "section": "Observations & Compliance",
        "question": "How many observations have you personally identified during this period?",
        "type": "number",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 5, 10)",
    },
    {
        "id": "L1Q7",
        "section": "Observations & Compliance",
        "question": "How many observations has your team identified during this period?",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 5, 10)",
    },
    {
        "id": "L1Q8",
        "section": "Process & Quality",
        "question": "How many audit checklists or RCMs have you updated during this period?",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 3, 7)",
    },
    {
        "id": "L1Q9",
        "section": "Client Relations",
        "question": "How many positive client feedbacks have you or your team received?",
        "type": "number",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 2, 5)",
    },
    {
        "id": "L1Q10",
        "section": "Client Relations",
        "question": "How many negative client feedbacks or escalations have you or your team received?",
        "type": "number",
        "weightage": 5,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 1, 2)",
    },
    {
        "id": "L1Q11",
        "section": "Team",
        "question": "How would you rate yourself on managing team attrition during this period?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L1Q12",
        "section": "Process & Quality",
        "question": "How would you rate yourself on minimizing quality missouts in your work?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L1Q13",
        "section": "Project Delivery",
        "question": "How would you rate yourself on adherence to project plans?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL 2 QUESTIONS  (Sheet: '2')
# Designations: Sr Audit Executive, Mangement & Audit Trainee, Management Trainee,
#               Article, Audit Executive, Analyst, Article Assistant,
#               Article Assistant-New, System Auditor, CMA Article
# ─────────────────────────────────────────────────────────────────────────────
LEVEL_2_QUESTIONS: list[dict] = [
    {
        "id": "L2Q1",
        "section": "Project Delivery",
        "question": "How many projects have you worked on during this assessment period?",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter the number of projects and a brief description of each",
    },
    {
        "id": "L2Q2",
        "section": "Project Delivery",
        "question": "How would you rate yourself on timely completion and upload of project documentation?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L2Q3",
        "section": "Project Delivery",
        "question": "How would you rate yourself on providing timely status updates to your team and manager?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L2Q4",
        "section": "Observations & Compliance",
        "question": "How would you rate yourself on avoiding observations that lead to regulatory non-compliance (e.g., Fines & Penalties)?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L2Q5",
        "section": "Observations & Compliance",
        "question": "How many observations have you personally identified during this period?",
        "type": "number",
        "weightage": 15,
        "required": True,
        "response_hint": "Enter a number (e.g., 0, 5, 10)",
    },
    {
        "id": "L2Q6",
        "section": "Observations & Compliance",
        "question": "What is the total number of controls tested or audit checkpoints tested across all reports issued during this period?",
        "type": "number",
        "weightage": 10,
        "required": True,
        "response_hint": "Enter a number (e.g., 10, 50, 100)",
    },
    {
        "id": "L2Q7",
        "section": "Process & Quality",
        "question": "How would you rate yourself on minimizing quality missouts in your work?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L2Q8",
        "section": "Project Delivery",
        "question": "How would you rate yourself on completing project plans within the defined timelines?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "L2Q9",
        "section": "Project Delivery",
        "question": "How would you rate yourself on avoiding delays in project delivery?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
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
            "question": "How would you rate yourself on handling escalated issues from L1 effectively?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_722_2",
            "section": "System Administration",
            "question": "How would you rate yourself on managing servers, OS, patching, and overall system performance?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_722_3",
            "section": "Network Management",
            "question": "How would you rate yourself on monitoring and troubleshooting LAN/WAN, firewall, and routing issues?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_722_4",
            "section": "Email & Server Management",
            "question": "How would you rate yourself on administering email servers and file systems?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_722_5",
            "section": "Backup & Recovery",
            "question": "How would you rate yourself on ensuring backup jobs run successfully and performing recovery testing?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_722_6",
            "section": "Security Management",
            "question": "How would you rate yourself on managing AD, permissions, policies, and endpoint security?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_722_7",
            "section": "License Management",
            "question": "How would you rate yourself on ensuring software compliance and timely license renewals?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_722_8",
            "section": "Documentation",
            "question": "How would you rate yourself on maintaining SOPs and technical documentation?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── IT Department — JHS1361 — 7 questions ────────────────────────────────
    "JHS1361": [
        {
            "id": "E_1361_1",
            "section": "Technical Support",
            "question": "How would you rate yourself on providing first-level support for hardware, software, and peripherals?",
            "type": "rating",
            "weightage": 25,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1361_2",
            "section": "Ticket Handling",
            "question": "How would you rate yourself on logging, tracking, and resolving IT tickets within SLA?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1361_3",
            "section": "System Setup",
            "question": "How would you rate yourself on installing and configuring desktops, laptops, and printers?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1361_4",
            "section": "Basic Network Troubleshooting",
            "question": "How would you rate yourself on resolving LAN/WiFi and basic connectivity issues?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1361_5",
            "section": "Asset Management",
            "question": "How would you rate yourself on maintaining IT asset inventory and records?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1361_6",
            "section": "User Support",
            "question": "How would you rate yourself on assisting users with email, login, and software issues?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1361_7",
            "section": "Antivirus & Updates",
            "question": "How would you rate yourself on ensuring all endpoints are kept updated and protected?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Automation Team — JHS1191 (Data Scientist) — 11 questions ────────────
    "JHS1191": [
        {
            "id": "E_1191_1",
            "section": "Project Summary",
            "question": "How many projects have you completed during this assessment period?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 3)",
        },
        {
            "id": "E_1191_2",
            "section": "Project Summary",
            "question": "How many projects are currently ongoing?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 2)",
        },
        {
            "id": "E_1191_3",
            "section": "Data Discovery",
            "question": "How would you rate yourself on establishing the Data Discovery function effectively (team setup, workflow, project initiation within timelines)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_4",
            "section": "Dashboards",
            "question": "How would you rate yourself on developing or migrating dashboards (Power BI or others) as per targets with minimal downtime?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_5",
            "section": "Dashboards",
            "question": "How would you rate the user-friendliness of your dashboards and the level of stakeholder satisfaction achieved?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_6",
            "section": "Automation",
            "question": "How would you rate yourself on delivering automation initiatives with measurable impact (e.g., hours saved per year)?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_7",
            "section": "Audit Innovation",
            "question": "How would you rate yourself on implementing and driving adoption of audit innovation initiatives such as sampling tools or methods?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_8",
            "section": "Collaboration",
            "question": "How would you rate yourself on collaborating effectively with HIU, HR, and efficiency teams to deliver strategic projects?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_9",
            "section": "Application Projects",
            "question": "How would you rate yourself on executing application projects smoothly (low bugs, timely fixes, performance improvements, client onboarding)?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_10",
            "section": "Code Management",
            "question": "How would you rate yourself on code management practices (version control, backups, zero data loss, compliance)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1191_11",
            "section": "Professional Conduct",
            "question": "How would you rate yourself on maintaining training, knowledge sharing, and professional conduct as per expectations?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Automation Team — JHS1283 — 11 questions ─────────────────────────────
    "JHS1283": [
        {
            "id": "E_1283_1",
            "section": "Project Summary",
            "question": "How many projects have you completed during this assessment period?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 3)",
        },
        {
            "id": "E_1283_2",
            "section": "Project Summary",
            "question": "How many projects are currently ongoing?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 2)",
        },
        {
            "id": "E_1283_3",
            "section": "Delivery",
            "question": "How would you rate yourself on delivering features on time as per sprint or project timelines?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_4",
            "section": "Frontend",
            "question": "How would you rate yourself on implementing the frontend (HTML/CSS/JS/React) with responsive design and minimal UI bugs?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_5",
            "section": "Backend",
            "question": "How would you rate yourself on developing backend APIs (FastAPI) with proper structure, validation, and performance?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_6",
            "section": "Database",
            "question": "How would you rate yourself on optimizing database design (MongoDB) for performance, scalability, and correct data handling?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_7",
            "section": "Code Quality",
            "question": "How would you rate yourself on maintaining code quality (readability, modularity, reusability, minimal rework)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_8",
            "section": "Version Control",
            "question": "How would you rate yourself on following version control practices (Git/GitHub) with clean commits, branching, and PRs?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_9",
            "section": "Deployment",
            "question": "How would you rate yourself on handling application deployments with minimal downtime or issues?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_10",
            "section": "Bug Resolution",
            "question": "How would you rate yourself on resolving bugs and issues within defined timelines with proper root cause fixes?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1283_11",
            "section": "Documentation",
            "question": "How would you rate yourself on creating and maintaining documentation such as API docs and setup guides?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Other Shared Services — JHS963 (BDE) — 11 questions ──────────────────
    "JHS963": [
        {
            "id": "E_963_1",
            "section": "Customer Acquisition",
            "question": "How many qualified leads did you generate during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 10, 25, 50)",
        },
        {
            "id": "E_963_2",
            "section": "Customer Acquisition",
            "question": "How many leads were successfully converted into business opportunities?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 2, 5, 10)",
        },
        {
            "id": "E_963_3",
            "section": "Knowledge Series",
            "question": "How many webinars or events did you conduct during this period?",
            "type": "number",
            "weightage": 5,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 3, 5)",
        },
        {
            "id": "E_963_4",
            "section": "Content & Digital Presence",
            "question": "How many content pieces (posts, videos, creatives) did you publish during this period?",
            "type": "number",
            "weightage": 5,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 15, 30)",
        },
        {
            "id": "E_963_5",
            "section": "Proposals & Tenders",
            "question": "How many proposals or tender submissions did you complete during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 3, 5)",
        },
        {
            "id": "E_963_6",
            "section": "Marketing & Campaigns",
            "question": "How would you rate yourself on executing marketing and communication campaigns on time and achieving engagement targets?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_963_7",
            "section": "CRM & Database Management",
            "question": "How would you rate yourself on keeping the CRM database updated accurately with relevant and usable contact data?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_963_8",
            "section": "Client Engagement",
            "question": "How would you rate yourself on executing client engagement activities and capturing feedback effectively?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_963_9",
            "section": "Internal Coordination",
            "question": "How would you rate yourself on coordinating with internal teams smoothly and delivering tasks on time?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_963_10",
            "section": "Performance Tracking",
            "question": "How would you rate yourself on tracking performance metrics and submitting reports regularly with actionable improvements?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_963_11",
            "section": "Process & Quality",
            "question": "How would you rate yourself on overall work quality, meeting deadlines, and minimizing rework?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Other Shared Services — JHS1176 (BDE) — 11 questions ─────────────────
    "JHS1176": [
        {
            "id": "E_1176_1",
            "section": "Customer Acquisition",
            "question": "How many qualified leads did you generate during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 10, 25, 50)",
        },
        {
            "id": "E_1176_2",
            "section": "Customer Acquisition",
            "question": "How many leads were successfully converted into business opportunities?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 2, 5, 10)",
        },
        {
            "id": "E_1176_3",
            "section": "Knowledge Series",
            "question": "How many knowledge sessions or webinars did you conduct during this period?",
            "type": "number",
            "weightage": 5,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 3, 5)",
        },
        {
            "id": "E_1176_4",
            "section": "Content & Digital Presence",
            "question": "How many content pieces (LinkedIn posts, YouTube videos, creatives) did you publish during this period?",
            "type": "number",
            "weightage": 5,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 15, 30)",
        },
        {
            "id": "E_1176_5",
            "section": "Proposals & Tenders",
            "question": "How many proposals, empanelments, or tenders did you complete during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 3, 5)",
        },
        {
            "id": "E_1176_6",
            "section": "Marketing & Campaigns",
            "question": "How would you rate yourself on executing marketing and communication campaigns consistently and achieving defined engagement targets?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1176_7",
            "section": "CRM & Database Management",
            "question": "How would you rate yourself on maintaining the CRM and database accurately with regular updates and relevant decision-maker data?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1176_8",
            "section": "Client Engagement",
            "question": "How would you rate yourself on executing client engagement activities effectively and capturing feedback?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1176_9",
            "section": "Internal Coordination",
            "question": "How would you rate yourself on internal coordination and timely execution of tasks and deliverables?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1176_10",
            "section": "Performance Tracking",
            "question": "How would you rate yourself on tracking performance metrics and submitting reports regularly with actionable insights?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1176_11",
            "section": "Process & Quality",
            "question": "How would you rate yourself on overall work quality, meeting deadlines, and minimizing rework?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    "JHS1297": [
        {
            "id": "E_1297_1",
            "section": "Customer Acquisition",
            "question": "How many qualified leads did you generate during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 10, 25, 50)",
        },
        {
            "id": "E_1297_2",
            "section": "Customer Acquisition",
            "question": "How many leads were successfully converted into business opportunities?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 2, 5, 10)",
        },
        {
            "id": "E_1297_3",
            "section": "Knowledge Series",
            "question": "How many knowledge sessions or webinars did you conduct during this period?",
            "type": "number",
            "weightage": 5,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 3, 5)",
        },
        {
            "id": "E_1297_4",
            "section": "Content & Digital Presence",
            "question": "How many content pieces (LinkedIn posts, YouTube videos, creatives) did you publish during this period?",
            "type": "number",
            "weightage": 5,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 15, 30)",
        },
        {
            "id": "E_1297_5",
            "section": "Proposals & Tenders",
            "question": "How many proposals, empanelments, or tenders did you complete during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 3, 5)",
        },
        {
            "id": "E_1297_6",
            "section": "Marketing & Campaigns",
            "question": "How would you rate yourself on executing marketing and communication campaigns consistently and achieving defined engagement targets?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1297_7",
            "section": "CRM & Database Management",
            "question": "How would you rate yourself on maintaining the CRM and database accurately with regular updates and relevant decision-maker data?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1297_8",
            "section": "Client Engagement",
            "question": "How would you rate yourself on executing client engagement activities effectively and capturing feedback?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1297_9",
            "section": "Internal Coordination",
            "question": "How would you rate yourself on internal coordination and timely execution of tasks and deliverables?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1297_10",
            "section": "Performance Tracking",
            "question": "How would you rate yourself on tracking performance metrics and submitting reports regularly with actionable insights?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1297_11",
            "section": "Process & Quality",
            "question": "How would you rate yourself on overall work quality, meeting deadlines, and minimizing rework?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Other Shared Services — JHS1303 (Knowledge & Special Projects) — 10 Qs
    "JHS1303": [
        {
            "id": "E_1303_1",
            "section": "Content Delivery",
            "question": "How many articles did you publish during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 10, 20, 30)",
        },
        {
            "id": "E_1303_2",
            "section": "Knowledge Sessions",
            "question": "How many knowledge sessions did you conduct during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 3, 5)",
        },
        {
            "id": "E_1303_3",
            "section": "Regulatory Updates",
            "question": "How many regulatory updates did you track and incorporate during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 10, 20)",
        },
        {
            "id": "E_1303_4",
            "section": "Special Projects",
            "question": "How many special projects did you complete during this period?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 1, 2, 3)",
        },
        {
            "id": "E_1303_5",
            "section": "Knowledge Repository",
            "question": "How would you rate yourself on maintaining the knowledge repository with high accuracy and regular updates?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1303_6",
            "section": "Content Quality",
            "question": "How would you rate yourself on maintaining content quality with strong peer review scores?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1303_7",
            "section": "Repository Usage",
            "question": "How would you rate yourself on improving repository usage and driving engagement growth?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1303_8",
            "section": "Quality Standards",
            "question": "How would you rate yourself on consistently following quality standards (version control, audits, archiving)?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1303_9",
            "section": "Compliance",
            "question": "How would you rate yourself on maintaining compliance with zero delays in updates and adherence to standards?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1303_10",
            "section": "Professional Conduct",
            "question": "How would you rate yourself on maintaining professional conduct with no complaints and strong workplace behavior?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Other Shared Services — JHS911 (Executive Assistant) — 10 questions ───
    "JHS911": [
        {
            "id": "E_911_1",
            "section": "Meeting Management",
            "question": "How many meetings did you coordinate and document (with MOMs) during this period?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 10, 20, 40)",
        },
        {
            "id": "E_911_2",
            "section": "Recruitment Coordination",
            "question": "How many interview schedules did you coordinate during this period?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 15, 30)",
        },
        {
            "id": "E_911_3",
            "section": "Offer & Joining",
            "question": "How many offer letters were rolled out and joining formalities coordinated during this period?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 2, 5, 10)",
        },
        {
            "id": "E_911_4",
            "section": "Calendar & Scheduling",
            "question": "How would you rate yourself on managing the Founder's calendar accurately with no overlaps and proactive planning?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_911_5",
            "section": "Communication",
            "question": "How would you rate yourself on handling communication professionally with timely responses, strong follow-ups, and zero escalations?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_911_6",
            "section": "Meeting Management",
            "question": "How would you rate yourself on managing meetings effectively — sharing agendas in advance, circulating MOMs within 24 hours, and maintaining accurate documentation?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_911_7",
            "section": "Strategic Support",
            "question": "How would you rate yourself on delivering strategic and administrative support efficiently (travel, approvals, task completion, proactive risk identification)?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_911_8",
            "section": "Recruitment Coordination",
            "question": "How would you rate yourself on handling end-to-end recruitment coordination with timely scheduling and no errors?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_911_9",
            "section": "Recruitment Tracking",
            "question": "How would you rate yourself on maintaining recruitment tracking accurately with real-time updates and zero data gaps?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_911_10",
            "section": "Operational Independence",
            "question": "How would you rate yourself on reducing the Founder's operational dependency through proactive execution and ownership?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Accounts — JHS48 (Sr Executive Accounts & Finance) — 10 questions ────
    "JHS48": [
        {
            "id": "E_48_1",
            "section": "Financial Leadership",
            "question": "How would you rate yourself on leading financial strategy, overseeing accounting operations, and ensuring compliance with financial regulations?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_2",
            "section": "Reporting",
            "question": "How would you rate yourself on supervising monthly, quarterly, and annual book closings and ensuring accuracy in financial reporting?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_3",
            "section": "Compliance",
            "question": "How would you rate yourself on timely filing of GST, TDS, PF, PT, and other statutory returns?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_4",
            "section": "Team Management",
            "question": "How would you rate yourself on supervising the accounts and shared services team and reviewing their work for accuracy and compliance?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_5",
            "section": "Reporting",
            "question": "How would you rate yourself on reviewing and finalizing books of accounts, P&L, balance sheets, and financial reports?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_6",
            "section": "Reporting",
            "question": "How would you rate yourself on ensuring timely and accurate monthly/quarterly MIS reports to the Sr. Partner?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_7",
            "section": "Operations",
            "question": "How would you rate yourself on tracking service billing and vendor payments?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_8",
            "section": "Innovation",
            "question": "How would you rate yourself on driving automation and digitization of accounting processes?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_9",
            "section": "Budgeting",
            "question": "How would you rate yourself on budget vs actual tracking and variance analysis?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_48_10",
            "section": "Compliance",
            "question": "How would you rate yourself on maintaining the Consolidated Compliance Tracker accurately and submitting it on time?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── Accounts — JHS266 — 8 questions ──────────────────────────────────────
    "JHS266": [
        {
            "id": "E_266_1",
            "section": "Daily Operations",
            "question": "How would you rate yourself on preparing and maintaining daily accounting records and vouchers?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_266_2",
            "section": "Reconciliation",
            "question": "How would you rate yourself on assisting with bank reconciliations, ledger scrutiny, and journal entries?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_266_3",
            "section": "Month-End",
            "question": "How would you rate yourself on supporting month-end closing activities and reconciliation of books?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_266_4",
            "section": "Billing",
            "question": "How would you rate yourself on monthly billing and raising invoices to clients accurately and on time?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_266_5",
            "section": "Operations",
            "question": "How would you rate yourself on maintaining expense reports and petty cash?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_266_6",
            "section": "Compliance",
            "question": "How would you rate yourself on generating UDIN in a timely and accurate manner?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_266_7",
            "section": "Cost Management",
            "question": "How would you rate yourself on participating in cost-saving initiatives and tracking routine operational expenses?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_266_8",
            "section": "Reporting",
            "question": "How would you rate yourself on preparing and sharing the weekly Debtors MIS report with management?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── HR Department — JHS1423 (Talent Acquisition Specialist) — 10 questions ─
    "JHS1423": [
        {
            "id": "E_1423_1",
            "section": "Recruitment Volume",
            "question": "How many positions were assigned to you for closure this quarter?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 10, 20)",
        },
        {
            "id": "E_1423_2",
            "section": "Recruitment Volume",
            "question": "How many positions did you successfully close this quarter?",
            "type": "number",
            "weightage": 10,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 10, 15)",
        },
        {
            "id": "E_1423_3",
            "section": "Recruitment Volume",
            "question": "How many candidates were interviewed (across all stages) this quarter?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 20, 50, 100)",
        },
        {
            "id": "E_1423_4",
            "section": "Recruitment",
            "question": "How would you rate yourself on managing the end-to-end recruitment lifecycle (sourcing, screening, interviewing, selection, and salary confirmations)?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1423_5",
            "section": "Coordination",
            "question": "How would you rate yourself on maintaining timely coordination with hiring managers and interview panels?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1423_6",
            "section": "Reporting",
            "question": "How would you rate yourself on tracking, maintaining, and updating recruitment data, dashboards, and MIS reports?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1423_7",
            "section": "TAT Compliance",
            "question": "How would you rate yourself on adhering to TAT (Turnaround Time) for each position from requisition to closure?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1423_8",
            "section": "Employer Branding",
            "question": "How would you rate yourself on contributing to employer branding activities on social platforms and through hiring campaigns?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1423_9",
            "section": "Meetings",
            "question": "How would you rate yourself on conducting weekly recruitment meetings and MOMs with hiring partners and sharing the weekly recruitment MIS?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_1423_10",
            "section": "Process Improvement",
            "question": "How would you rate yourself on suggesting recruitment process improvements or automation initiatives?",
            "type": "rating",
            "weightage": 5,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],

    # ── HR Department — JHS729 (Payroll Executive) — 11 questions ────────────
    "JHS729": [
        {
            "id": "E_729_1",
            "section": "Payroll Processing",
            "question": "How many employees' payroll did you process this month?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 50, 100, 200)",
        },
        {
            "id": "E_729_2",
            "section": "FNF Processing",
            "question": "How many Full and Final (FNF) settlements did you process this period?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 2, 5, 10)",
        },
        {
            "id": "E_729_3",
            "section": "Employee Relations",
            "question": "How many payroll-related employee queries or grievances did you resolve this period?",
            "type": "number",
            "weightage": 0,
            "required": True,
            "response_hint": "Enter a number (e.g., 5, 10, 20)",
        },
        {
            "id": "E_729_4",
            "section": "Payroll Processing",
            "question": "How would you rate yourself on ensuring accurate and timely processing of payroll for all employees?",
            "type": "rating",
            "weightage": 20,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_729_5",
            "section": "Compliance",
            "question": "How would you rate yourself on maintaining payroll records and ensuring compliance with statutory and company policies?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_729_6",
            "section": "Coordination",
            "question": "How would you rate yourself on coordinating with HR and HRMS for payroll inputs such as attendance and deductions?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_729_7",
            "section": "FNF Processing",
            "question": "How would you rate yourself on ensuring accurate and timely processing of Full and Final (FNF) settlements?",
            "type": "rating",
            "weightage": 15,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_729_8",
            "section": "Documentation",
            "question": "How would you rate yourself on preparing Appointment and Increment Letters for employees?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_729_9",
            "section": "SSP Portal",
            "question": "How would you rate yourself on timely and accurate updates on the SSP portal for Articles and CAs?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_729_10",
            "section": "OPE Processing",
            "question": "How would you rate yourself on ensuring accurate and timely processing of OPE for all employees?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
        {
            "id": "E_729_11",
            "section": "NAPS/NATS",
            "question": "How would you rate yourself on ensuring smooth, accurate, and timely NAPS/NATS contributions on a monthly basis?",
            "type": "rating",
            "weightage": 10,
            "required": True,
            "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
        },
    ],
}

# ── Cybersecurity Analyst — role-based (designation match) — 9 questions ─────
# Applies to designation "Cybersecurity Analyst" if no emp-code match
CYBERSECURITY_QUESTIONS: list[dict] = [
    {
        "id": "CY1",
        "section": "VA/PT Assessments",
        "question": "How would you rate yourself on completing VA/PT assessments as per plan with high accuracy in findings?",
        "type": "rating",
        "weightage": 20,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY2",
        "section": "ITGC Reviews",
        "question": "How would you rate yourself on completing ITGC reviews fully and reducing control gaps?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY3",
        "section": "Cybersecurity Audits",
        "question": "How would you rate yourself on conducting cybersecurity audits with high compliance and no major issues?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY4",
        "section": "SOC Reports",
        "question": "How would you rate yourself on delivering SOC1/SOC2 reports on time with high client satisfaction?",
        "type": "rating",
        "weightage": 15,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY5",
        "section": "Reporting",
        "question": "How would you rate yourself on producing accurate reporting and documentation with zero rework?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY6",
        "section": "Audit Closure",
        "question": "How would you rate yourself on closing audit observations within defined timelines?",
        "type": "rating",
        "weightage": 10,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY7",
        "section": "Process Improvement",
        "question": "How would you rate yourself on contributing to process improvements or methodology enhancements?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY8",
        "section": "Upskilling",
        "question": "How would you rate yourself on completing required upskilling programs and certifications?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
    },
    {
        "id": "CY9",
        "section": "Coordination",
        "question": "How would you rate yourself on coordinating with clients and teams smoothly and in a timely manner?",
        "type": "rating",
        "weightage": 5,
        "required": True,
        "response_hint": "Rate yourself — 1 (needs improvement) to 5 (excellent)",
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