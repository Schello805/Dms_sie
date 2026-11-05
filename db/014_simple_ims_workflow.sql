-- New interface policy; existing release history and content hashes remain unchanged.
ALTER TABLE document_versions ADD COLUMN approval_based_validity boolean NOT NULL DEFAULT false;
UPDATE document_versions SET approval_based_validity=true WHERE status='DRAFT';
CREATE TABLE document_upload_origins (
 document_id bigint PRIMARY KEY REFERENCES documents(id),
 uploaded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO document_upload_origins(document_id,uploaded_at)
 SELECT v.document_id,min(f.created_at) FROM document_versions v JOIN version_files vf ON vf.version_id=v.id
 JOIN file_objects f ON f.id=vf.file_id GROUP BY v.document_id;
CREATE TRIGGER immutable_upload_origin BEFORE UPDATE OR DELETE ON document_upload_origins FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TABLE release_validity (
 version_id bigint PRIMARY KEY REFERENCES document_versions(id),
 approved_at timestamptz NOT NULL,review_due_on date NOT NULL,
 interval_months integer NOT NULL CHECK(interval_months BETWEEN 1 AND 1200)
);
CREATE TRIGGER immutable_release_validity BEFORE UPDATE OR DELETE ON release_validity FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE OR REPLACE VIEW version_review_status AS
SELECT v.id AS version_id,COALESCE(success.next_review_on,rv.review_due_on,v.next_review_on) AS review_due_on,
 (COALESCE(latest.reviewed_at,initial_review.reviewed_at) AT TIME ZONE 'Europe/Berlin')::date AS last_review_on,
 latest.result AS review_result
FROM document_versions v LEFT JOIN release_validity rv ON rv.version_id=v.id
LEFT JOIN LATERAL (SELECT reviewed_at,result FROM periodic_reviews pr WHERE pr.version_id=v.id ORDER BY pr.id DESC LIMIT 1) latest ON true
LEFT JOIN LATERAL (SELECT next_review_on FROM periodic_reviews pr WHERE pr.version_id=v.id AND pr.result='UNCHANGED' ORDER BY pr.id DESC LIMIT 1) success ON true
LEFT JOIN LATERAL (SELECT max(r.decided_at) AS reviewed_at FROM approval_decisions r
 WHERE r.version_id=v.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
 AND EXISTS(SELECT 1 FROM approval_decisions a WHERE a.workflow_id=r.workflow_id AND a.stage='APPROVAL' AND a.decision='ACCEPT')) initial_review ON true;
-- A passed review date is a visible overdue state, never an implicit withdrawal.
CREATE OR REPLACE FUNCTION can_read_version(subject bigint,target_version bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT can_lead_approve(subject,target_version) OR EXISTS (
 SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id
 WHERE v.id=target_version AND can_access_version(subject,v.id) AND (
 has_role(subject,'AUTHOR',d.responsible_department_id,d.id)
 OR has_role(subject,'REVIEWER',d.responsible_department_id,d.id)
 OR (has_role(subject,'READER',d.responsible_department_id,d.id) AND v.id=current_release(d.id) AND v.status='APPROVED')));
$$;
INSERT INTO document_categories(name) VALUES ('SOP') ON CONFLICT DO NOTHING;
-- Operational roles have three public labels. Legacy qualifications remain historical snapshots.
UPDATE users SET qmb_role='PRIMARY',qmb_approval_lead=false WHERE qmb_approval_lead;

CREATE FUNCTION guard_workflow_policy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.approval_based_validity IS DISTINCT FROM OLD.approval_based_validity AND OLD.status<>'DRAFT' THEN
 RAISE EXCEPTION 'Workflow policy is frozen after submission'; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER protect_workflow_policy BEFORE UPDATE OF approval_based_validity ON document_versions
FOR EACH ROW EXECUTE FUNCTION guard_workflow_policy();
CREATE FUNCTION set_operational_roles(actor bigint,target bigint,author_role boolean,qmb_role boolean,admin_role boolean,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE previous jsonb;
BEGIN
 IF NOT public.has_role(actor,'ADMIN',NULL,NULL) THEN RAISE EXCEPTION 'Active IT administrator required'; END IF;
 IF length(trim(why))=0 THEN RAISE EXCEPTION 'Reason required'; END IF;
 IF actor=target AND NOT admin_role THEN RAISE EXCEPTION 'Cannot revoke own administrator access'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ims-user-roles'));
 IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.auth_user a ON a.id=u.auth_user_id WHERE u.id=target AND u.active AND a.is_active) THEN
 RAISE EXCEPTION 'Active account required'; END IF;
 IF EXISTS(SELECT 1 FROM public.role_assignments r JOIN public.group_memberships m ON m.group_id=r.group_id
 JOIN public.dms_groups g ON g.id=r.group_id AND g.active WHERE m.user_id=target AND r.role IN ('AUTHOR','ADMIN')) THEN
 RAISE EXCEPTION 'Inherited group roles must be managed separately'; END IF;
 SELECT jsonb_build_object('admin',settings_admin,'qmb',u.qmb_role,'author',public.has_role(target,'AUTHOR',NULL,NULL),'assignments',COALESCE((SELECT jsonb_agg(jsonb_build_object('role',r.role,'department_id',r.department_id,'document_id',r.document_id)) FROM public.role_assignments r WHERE r.user_id=target),'[]'::jsonb)) INTO previous FROM public.users u WHERE id=target FOR UPDATE;
 DELETE FROM public.role_assignments WHERE user_id=target AND role IN ('AUTHOR','REVIEWER','ADMIN');
 INSERT INTO public.role_assignments(user_id,role) VALUES(target,'READER') ON CONFLICT DO NOTHING;
 IF author_role THEN INSERT INTO public.role_assignments(user_id,role) VALUES(target,'AUTHOR'); END IF;
 UPDATE public.users SET settings_admin=admin_role,qmb_role=CASE WHEN set_operational_roles.qmb_role THEN 'PRIMARY' ELSE 'NONE' END,qmb_approval_lead=false WHERE id=target;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
 VALUES(actor,'CHANGE_USER_ROLES','user',target::text,why,jsonb_build_object('before',previous,'after',jsonb_build_object('author',author_role,'qmb',qmb_role,'admin',admin_role)));
END;
$$;
REVOKE ALL ON FUNCTION set_operational_roles(bigint,bigint,boolean,boolean,boolean,text) FROM PUBLIC;
-- Old lead markers remain historical only; operational approval now requires QMB.
CREATE OR REPLACE FUNCTION can_lead_approve(subject bigint,target_version bigint) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT false; $$;
CREATE OR REPLACE FUNCTION verify_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status='APPROVED' AND OLD.status<>'APPROVED' THEN
 IF NOT EXISTS(SELECT 1 FROM workflow_instances w
 JOIN approval_decisions r ON r.workflow_id=w.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
 JOIN approval_decisions a ON a.workflow_id=w.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'
 WHERE w.version_id=NEW.id AND w.closed_at IS NULL AND r.version_id=NEW.id AND a.version_id=NEW.id
 AND r.content_fingerprint=w.content_fingerprint AND a.content_fingerprint=w.content_fingerprint
 AND r.actor_id=a.actor_id AND is_qmb(a.actor_id)
 AND r.actor_id<>NEW.created_by AND r.actor_id<>w.submitted_by
 AND r.qmb_role_at_decision IS NOT NULL AND a.qmb_role_at_decision IS NOT NULL)
 THEN RAISE EXCEPTION 'Independent active QMB decision required'; END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE OR REPLACE FUNCTION current_release(target_document bigint) RETURNS bigint LANGUAGE sql STABLE AS $$
 WITH latest AS (
 SELECT v.id,v.status FROM document_versions v WHERE v.document_id=target_document
 AND v.status IN ('APPROVED','ARCHIVED') AND v.effective_from<=statement_timestamp()
 AND NOT EXISTS(SELECT 1 FROM document_withdrawals w WHERE w.document_id=v.document_id
 AND w.withdrawn_at>=COALESCE((SELECT max(a.decided_at) FROM approval_decisions a
 WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'),v.created_at))
 ORDER BY v.effective_from DESC,v.major DESC,v.minor DESC LIMIT 1
 ) SELECT id FROM latest WHERE status='APPROVED';
$$;
