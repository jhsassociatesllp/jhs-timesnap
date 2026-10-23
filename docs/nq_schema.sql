-- docs/nq_schema.sql
-- REDUCED schema used ONLY for local development and tests (loaded into the Docker MySQL).
-- It is NOT a dump of the real Nexus Quant database: it lists just the tables and columns that
-- Timesnap reads (see backend/nq/repository.py) and deliberately leaves out everything else.
-- The real NQ structure is kept out of this repository; ask the NQ owner if you need it.
--
-- Conventions seen in NQ: enum('0','1') flags stored as strings; is_deleted = soft delete;
-- assigned_to / project_manager hold NQ user ids (a single id or a comma-separated list).

CREATE TABLE `tbl_client` (
  `id` int NOT NULL AUTO_INCREMENT,
  `client_id` varchar(100) DEFAULT NULL,
  `client_name` varchar(200) DEFAULT NULL,
  `company_name` varchar(200) DEFAULT NULL,   -- the client's real name; tbl_projects.client_name holds this table's id
  `project_incharge` varchar(100) DEFAULT NULL,
  `status` enum('0','1') NOT NULL DEFAULT '1',
  `is_deleted` enum('0','1') NOT NULL DEFAULT '0',
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `tbl_user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `emp_id` varchar(25) DEFAULT NULL,            -- matches Timesnap Employee_details.EmpID
  `name` varchar(250) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `reporting_to` int DEFAULT NULL,
  `reporting_to_partner` int DEFAULT NULL,
  `role` int DEFAULT NULL,
  `status` enum('0','1') NOT NULL DEFAULT '1',
  `is_deleted` enum('0','1') NOT NULL DEFAULT '0',
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `tbl_project_status` (
  `id` int NOT NULL AUTO_INCREMENT,
  `status_name` varchar(100) DEFAULT NULL,
  `color` varchar(100) DEFAULT NULL,
  `status` enum('0','1') NOT NULL DEFAULT '1',
  `is_deleted` enum('0','1') NOT NULL DEFAULT '0',
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `tbl_project_task_status` (
  `id` int NOT NULL AUTO_INCREMENT,
  `status_name` varchar(100) DEFAULT NULL,      -- 1 To Do, 2 In Process, 3 Hold, 4 Complete
  `color` varchar(100) DEFAULT NULL,
  `status` enum('0','1') NOT NULL DEFAULT '1',
  `is_deleted` enum('0','1') NOT NULL DEFAULT '0',
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `tbl_projects` (
  `id` int NOT NULL AUTO_INCREMENT,
  `project_id` varchar(15) DEFAULT NULL,        -- the project code, e.g. PL-T001
  `client_name` varchar(100) DEFAULT NULL,      -- free text, not a foreign key
  `project_name` varchar(100) DEFAULT NULL,
  `category` varchar(100) DEFAULT NULL,         -- audit type, free text (e.g. Statutory Audit)
  `project_manager` varchar(100) DEFAULT NULL,  -- NQ user id(s)
  `project_partner` int DEFAULT NULL,
  `project_status` enum('0','1','2','3') DEFAULT '1' COMMENT '0=inactive,1=active,2=hold,3=closed',
  `start_date` date DEFAULT NULL COMMENT 'execution period',
  `end_date` date DEFAULT NULL COMMENT 'execution period',
  `status` enum('0','1') NOT NULL DEFAULT '1',
  `is_deleted` enum('0','1') NOT NULL DEFAULT '0',
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `tbl_project_tasks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `task_uid` varchar(25) DEFAULT NULL,
  `parent_task_id` int DEFAULT NULL COMMENT 'NULL = parent task, otherwise a sub-task of that task id',
  `project_id` int DEFAULT NULL,                -- tbl_projects.id
  `task_name` varchar(250) DEFAULT NULL,
  `start_date` date DEFAULT NULL,
  `end_date` date DEFAULT NULL,                 -- the ONLY column Timesnap may write back (Phase 4, off by default)
  `assigned_to` varchar(250) DEFAULT NULL,      -- NQ user id(s), e.g. '3' or '3,4'
  `task_status` int DEFAULT '1',                -- see tbl_project_task_status
  `is_complete` enum('0','1') NOT NULL DEFAULT '0',
  `status` enum('0','1') NOT NULL DEFAULT '1',
  `is_deleted` enum('0','1') NOT NULL DEFAULT '0',
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
