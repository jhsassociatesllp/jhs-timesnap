-- Dev-only MySQL users mirroring production privileges (dummy passwords).
-- nq_ro: SELECT only. nq_wb: SELECT + UPDATE on the task end_date column only.
CREATE USER 'nq_ro'@'%' IDENTIFIED BY 'dev_ro_pass';
GRANT SELECT ON jhsdb.* TO 'nq_ro'@'%';

CREATE USER 'nq_wb'@'%' IDENTIFIED BY 'dev_wb_pass';
GRANT SELECT ON jhsdb.* TO 'nq_wb'@'%';
GRANT UPDATE (end_date) ON jhsdb.tbl_project_tasks TO 'nq_wb'@'%';
FLUSH PRIVILEGES;
