-- Dedicated existing LOGIN role, no ownership or application-role membership.
-- psql -v notification_role=ims_dms_notify -v database_name=ims_dms -f db/notification_grants.sql
GRANT CONNECT ON DATABASE :"database_name" TO :"notification_role";
GRANT USAGE ON SCHEMA public TO :"notification_role";
GRANT SELECT ON notification_settings,review_notifications,documents,document_versions,
    users,role_assignments,dms_groups,group_memberships,document_access_users,
    document_access_groups,document_withdrawals,approval_decisions,periodic_reviews,
    effective_role_assignments,version_review_status TO :"notification_role";
GRANT SELECT (id,is_active,email) ON auth_user TO :"notification_role";
-- Row locking a version requires UPDATE privilege; grant only the immutable ID.
-- The worker never updates this column; released-row triggers still forbid mutation.
GRANT UPDATE (id) ON document_versions TO :"notification_role";
GRANT INSERT,UPDATE ON review_notifications TO :"notification_role";
GRANT INSERT ON audit_events TO :"notification_role";
GRANT USAGE ON SEQUENCE review_notifications_id_seq,audit_events_id_seq TO :"notification_role";
-- Permission evaluation for the separately designated QMB approval lead.
GRANT SELECT (id,version_id,closed_at,submitted_by) ON workflow_instances TO :"notification_role";
