-- Run as schema owner after migrations, using psql -v runtime_role=ims_dms_app.
-- The target role must already exist and must not own tables or inherit owner rights.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"runtime_role";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"runtime_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"runtime_role";
GRANT INSERT ON documents, document_versions, file_objects, version_files,
    version_departments, version_standard_links, workflow_instances,
    approval_decisions, audit_events, periodic_reviews TO :"runtime_role";
GRANT UPDATE (title, change_summary, effective_from, next_review_on, status)
    ON document_versions TO :"runtime_role";
GRANT UPDATE (closed_at) ON workflow_instances TO :"runtime_role";
GRANT DELETE ON version_files TO :"runtime_role";
GRANT INSERT, UPDATE, DELETE ON django_session TO :"runtime_role";
GRANT UPDATE (last_login) ON auth_user TO :"runtime_role";
GRANT DELETE ON version_departments, version_standard_links TO :"runtime_role";
GRANT UPDATE (access_mode) ON documents TO :"runtime_role";
GRANT UPDATE (classification) ON document_versions TO :"runtime_role";
GRANT INSERT, DELETE ON document_access_users, document_access_groups TO :"runtime_role";
GRANT INSERT ON document_withdrawals TO :"runtime_role";
GRANT INSERT, UPDATE ON file_text_indexes TO :"runtime_role";
GRANT UPDATE (review_interval_months,updated_at) ON document_categories TO :"runtime_role";
GRANT UPDATE ON notification_settings TO :"runtime_role";
GRANT INSERT, UPDATE ON review_notifications TO :"runtime_role";
GRANT UPDATE (email) ON users,auth_user TO :"runtime_role";
GRANT UPDATE(qmb_role) ON users TO :"runtime_role";
GRANT UPDATE(retention_months,storage_location_id) ON document_categories TO :"runtime_role";
GRANT INSERT,UPDATE ON storage_locations TO :"runtime_role";

GRANT UPDATE(qmb_approval_lead) ON users TO :"runtime_role";
GRANT INSERT,UPDATE ON audience_groups,user_workplaces,version_distribution TO :"runtime_role";
GRANT INSERT,DELETE ON audience_memberships,version_audiences,document_bookmarks TO :"runtime_role";
GRANT INSERT ON acknowledgement_assignments,acknowledgement_receipts,evidence_records,
 evidence_retention_events,evidence_disposal_requests TO :"runtime_role";
GRANT UPDATE(id) ON evidence_records TO :"runtime_role";
GRANT INSERT ON branding_revisions TO :"runtime_role";
GRANT UPDATE(revision_id) ON branding_settings TO :"runtime_role";
GRANT UPDATE ON directory_settings TO :"runtime_role";
GRANT INSERT ON document_upload_origins,release_validity TO :"runtime_role";

GRANT UPDATE(approval_based_validity) ON document_versions TO :"runtime_role";
GRANT EXECUTE ON FUNCTION set_operational_roles(bigint,bigint,boolean,boolean,boolean,text) TO :"runtime_role";
GRANT EXECUTE ON FUNCTION create_local_account(bigint,text,text,text,text,text),set_account_active(bigint,bigint,boolean,text),set_local_password(bigint,bigint,text,text) TO :"runtime_role";
