ALTER TABLE users ADD COLUMN qmb_approval_lead boolean NOT NULL DEFAULT false;
ALTER TABLE approval_decisions ADD COLUMN approval_lead_at_decision boolean NOT NULL DEFAULT false;
CREATE FUNCTION is_qmb_approval_lead(subject bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id
 WHERE u.id=subject AND u.active AND a.is_active AND u.qmb_approval_lead);
$$;
CREATE FUNCTION can_lead_approve(subject bigint,target_version bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT is_qmb_approval_lead(subject) AND EXISTS (
 SELECT 1 FROM document_versions v JOIN workflow_instances w ON w.version_id=v.id AND w.closed_at IS NULL
 JOIN approval_decisions r ON r.workflow_id=w.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
 WHERE v.id=target_version AND v.status='PENDING_APPROVAL' AND v.created_by<>subject
 AND w.submitted_by<>subject AND r.qmb_role_at_decision IS NOT NULL);
$$;
CREATE OR REPLACE FUNCTION can_read_version(subject bigint,target_version bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT can_lead_approve(subject,target_version) OR EXISTS (
 SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id
 WHERE v.id=target_version AND can_access_version(subject,v.id) AND (
 has_role(subject,'AUTHOR',d.responsible_department_id,d.id)
 OR has_role(subject,'REVIEWER',d.responsible_department_id,d.id)
 OR (has_role(subject,'READER',d.responsible_department_id,d.id)
 AND v.id=current_release(d.id) AND v.status='APPROVED' AND (v.valid_until IS NULL OR v.valid_until>now()))));
$$;
CREATE OR REPLACE FUNCTION verify_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status='APPROVED' AND OLD.status<>'APPROVED' THEN
 IF NOT EXISTS (
 SELECT 1 FROM workflow_instances w
 JOIN approval_decisions r ON r.workflow_id=w.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
 JOIN approval_decisions a ON a.workflow_id=w.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'
 WHERE w.version_id=NEW.id AND w.closed_at IS NULL AND r.version_id=NEW.id AND a.version_id=NEW.id
 AND r.content_fingerprint=w.content_fingerprint AND a.content_fingerprint=w.content_fingerprint
 AND r.actor_id<>NEW.created_by AND r.actor_id<>w.submitted_by
 AND a.actor_id<>NEW.created_by AND a.actor_id<>w.submitted_by
 AND r.qmb_role_at_decision IS NOT NULL
 AND ((r.actor_id=a.actor_id AND is_qmb(a.actor_id) AND a.qmb_role_at_decision IS NOT NULL)
 OR (is_qmb_approval_lead(a.actor_id) AND a.approval_lead_at_decision))
 ) THEN RAISE EXCEPTION 'Independent QMB review and authorized approval required'; END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE FUNCTION validate_decision_qualification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.stage='REVIEW' THEN
  IF NOT is_qmb(NEW.actor_id) OR NEW.qmb_role_at_decision IS DISTINCT FROM
    (SELECT qmb_role FROM users WHERE id=NEW.actor_id) THEN
   RAISE EXCEPTION 'Review requires a genuine active QMB qualification';
  END IF;
 ELSE
  IF NOT ((is_qmb(NEW.actor_id) AND NEW.qmb_role_at_decision IS NOT DISTINCT FROM
    (SELECT qmb_role FROM users WHERE id=NEW.actor_id))
    OR (is_qmb_approval_lead(NEW.actor_id) AND NEW.approval_lead_at_decision)) THEN
   RAISE EXCEPTION 'Approval requires genuine QMB or designated lead qualification';
  END IF;
 END IF;
 IF NEW.approval_lead_at_decision AND NOT is_qmb_approval_lead(NEW.actor_id) THEN
  RAISE EXCEPTION 'Invalid approval lead snapshot';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER decision_qualification BEFORE INSERT ON approval_decisions
FOR EACH ROW EXECUTE FUNCTION validate_decision_qualification();
