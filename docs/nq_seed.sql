-- docs/nq_seed.sql
-- FAKE development data for the Docker MySQL (loaded after docs/nq_schema.sql).
-- No real client, project or employee data. Reference "today" in tests: 2026-10-14.
-- Deliberate edge cases: comma-separated assignees (with and without spaces),
-- ids that share digits ('13' vs '3'), unassigned tasks, soft-deleted task/project/user,
-- overdue (open and done) tasks, sub-tasks, tasks with NULL dates, closed project.

INSERT INTO tbl_client (id, client_id, client_name, project_incharge, is_deleted, status, created_on) VALUES
 (1, 'C-T01', 'Test Client A', '1', '0', '1', '2026-01-01 00:00:00'),
 (2, 'C-T02', 'Test Client B', '1', '0', '1', '2026-01-01 00:00:00'),
 (3, 'C-T03', 'Deleted Client', '1', '1', '1', '2026-01-01 00:00:00');

INSERT INTO tbl_user (id, emp_id, name, email, reporting_to, reporting_to_partner, role, is_deleted, status, created_on) VALUES
 (1, 'JHS9001', 'Test Manager',    'manager@example.invalid',  2,    2, 2, '0', '1', '2026-01-01 00:00:00'),
 (2, 'JHS9000', 'Test Partner',    'partner@example.invalid',  NULL, NULL, 1, '0', '1', '2026-01-01 00:00:00'),
 (3, 'JHS9101', 'Test Employee 1', 'emp1@example.invalid',     1,    2, 3, '0', '1', '2026-01-01 00:00:00'),
 (4, 'JHS9102', 'Test Employee 2', 'emp2@example.invalid',     1,    2, 3, '0', '1', '2026-01-01 00:00:00'),
 (5, 'JHS9103', 'Test Employee 3', 'emp3@example.invalid',     1,    2, 3, '0', '1', '2026-01-01 00:00:00'),
 (6, 'JHS9104', 'Test Employee 4', 'emp4@example.invalid',     1,    2, 3, '0', '1', '2026-01-01 00:00:00'),
 (7, 'JHS9199', 'Deleted Employee','gone@example.invalid',     1,    2, 3, '1', '1', '2026-01-01 00:00:00');

INSERT INTO tbl_project_task_status (id, status_name, color, status, is_deleted, created_on) VALUES
 (1, 'To Do', '#999999', '1', '0', '2026-01-01 00:00:00'),
 (2, 'In Process', '#3366ff', '1', '0', '2026-01-01 00:00:00'),
 (3, 'Hold', '#ff9900', '1', '0', '2026-01-01 00:00:00'),
 (4, 'Complete', '#00aa00', '1', '0', '2026-01-01 00:00:00'),
 (12, 'New Requirement', '#cccccc', '1', '1', '2026-01-01 00:00:00');

INSERT INTO tbl_project_status (id, status_name, color, status, is_deleted, created_on) VALUES
 (1, 'Delayed', '#ff0000', '1', '1', '2026-01-01 00:00:00'),
 (2, 'Ongoing', '#3366ff', '1', '0', '2026-01-01 00:00:00'),
 (3, 'Hold', '#ff9900', '1', '0', '2026-01-01 00:00:00'),
 (4, 'Closed', '#00aa00', '1', '0', '2026-01-01 00:00:00');

-- project_status enum: 0 inactive, 1 active, 2 hold, 3 closed. project_manager holds NQ user id(s).
INSERT INTO tbl_projects (id, project_id, client_name, project_name, project_manager, project_partner, project_status, start_date, end_date, is_deleted, status, created_on) VALUES
 (1, 'PL-T001', 'Test Client A', 'Statutory Audit FY26',   '1',   2, '1', '2026-10-01', '2026-10-31', '0', '1', '2026-09-01 00:00:00'),
 (2, 'PL-T002', 'Test Client A', 'Internal Audit Q2',      '1',   2, '1', '2026-10-05', '2026-11-15', '0', '1', '2026-09-01 00:00:00'),
 (3, 'PL-T003', 'Test Client B', 'Tax Review',             '1,2', 2, '1', '2026-10-10', '2026-12-31', '0', '1', '2026-09-01 00:00:00'),
 (4, 'PL-T004', 'Test Client B', 'Deleted Project',        '1',   2, '1', '2026-10-01', '2026-10-31', '1', '1', '2026-09-01 00:00:00'),
 (5, 'PL-T005', 'Test Client B', 'Closed Project',         '1',   2, '3', '2026-01-01', '2026-03-31', '0', '1', '2026-01-01 00:00:00'),
 (6, 'PL-T006', 'Test Client A', 'Other Managers Project', '13',  2, '1', '2026-10-01', '2026-10-31', '0', '1', '2026-09-01 00:00:00');

-- task_status: 1 To Do, 2 In Process, 3 Hold, 4 Complete (is_complete=1 only for 4)
INSERT INTO tbl_project_tasks (id, task_uid, parent_task_id, project_id, task_name, start_date, end_date, assigned_to, task_status, is_complete, is_deleted, status, created_on) VALUES
 (1,  'T-001', NULL, 1, 'Planning and scoping',        '2026-10-01', '2026-10-31', '3',      2, '0', '0', '1', '2026-09-01 00:00:00'),
 (2,  'T-002', NULL, 1, 'Fieldwork week 2',            '2026-10-12', '2026-10-16', '3',      1, '0', '0', '1', '2026-09-01 00:00:00'),
 (3,  'T-003', NULL, 1, 'Overdue open task',           '2026-10-01', '2026-10-09', '3',      1, '0', '0', '1', '2026-09-01 00:00:00'),
 (4,  'T-004', NULL, 1, 'Overdue but done task',       '2026-10-01', '2026-10-05', '3',      4, '1', '0', '1', '2026-09-01 00:00:00'),
 (5,  'T-005', NULL, 2, 'Shared task (comma list)',    '2026-10-10', '2026-10-20', '3,4',    1, '0', '0', '1', '2026-09-01 00:00:00'),
 (6,  'T-006', NULL, 2, 'Shared task (comma + space)', '2026-10-10', '2026-10-20', '4, 5',   1, '0', '0', '1', '2026-09-01 00:00:00'),
 (7,  'T-007', NULL, 2, 'Unassigned task',             '2026-10-10', '2026-10-20', NULL,     1, '0', '0', '1', '2026-09-01 00:00:00'),
 (8,  'T-008', NULL, 2, 'Deleted task',                '2026-10-10', '2026-10-20', '4',      1, '0', '1', '1', '2026-09-01 00:00:00'),
 (9,  'T-009', 5,    3, 'Sub-task of T-005',           '2026-10-13', '2026-10-15', '4',      1, '0', '0', '1', '2026-09-01 00:00:00'),
 (10, 'T-010', NULL, 3, 'Future task',                 '2026-10-20', '2026-10-25', '5',      1, '0', '0', '1', '2026-09-01 00:00:00'),
 (11, 'T-011', NULL, 3, 'Task without dates',          NULL,         NULL,         '5',      1, '0', '0', '1', '2026-09-01 00:00:00'),
 (12, 'T-012', NULL, 4, 'Task in deleted project',     '2026-10-01', '2026-10-31', '3',      1, '0', '0', '1', '2026-09-01 00:00:00'),
 (13, 'T-013', NULL, 6, 'Assigned to user 13 only',    '2026-10-01', '2026-10-31', '13',     1, '0', '0', '1', '2026-09-01 00:00:00'),
 (14, 'T-014', NULL, 3, 'Task on hold',                '2026-10-01', '2026-10-31', '6',      3, '0', '0', '1', '2026-09-01 00:00:00'),
 (15, 'T-015', NULL, 5, 'Task in closed project',      '2026-01-05', '2026-03-20', '3',      4, '1', '0', '1', '2026-01-01 00:00:00');
