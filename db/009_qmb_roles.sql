ALTER TABLE users ADD COLUMN qmb_role text NOT NULL DEFAULT 'NONE' CHECK (qmb_role IN ('NONE','PRIMARY','DEPUTY'));
INSERT INTO role_assignments(user_id,group_id,role,department_id,document_id)
    SELECT user_id,group_id,'REVIEWER',department_id,document_id FROM role_assignments WHERE role='APPROVER'
    ON CONFLICT DO NOTHING;
DELETE FROM role_assignments WHERE role='APPROVER';
ALTER TABLE role_assignments DROP CONSTRAINT role_assignments_role_check;
ALTER TABLE role_assignments ADD CONSTRAINT role_assignments_role_check CHECK (role IN ('READER','AUTHOR','REVIEWER','ADMIN'));
ALTER TABLE role_assignments ADD CONSTRAINT admin_global_only CHECK (role<>'ADMIN' OR (department_id IS NULL AND document_id IS NULL));
ALTER TABLE approval_decisions ADD COLUMN qmb_role_at_decision text CHECK (qmb_role_at_decision IN ('PRIMARY','DEPUTY'));
CREATE FUNCTION is_qmb(subject bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id
        WHERE u.id=subject AND u.active AND a.is_active AND u.qmb_role IN ('PRIMARY','DEPUTY'));
$$;
CREATE OR REPLACE FUNCTION has_role(subject bigint,requested_role text,department bigint,target_document bigint DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id
        WHERE u.id=subject AND u.active AND a.is_active AND (
            (requested_role='REVIEWER' AND is_qmb(subject))
            OR (requested_role='ADMIN' AND u.settings_admin)
            OR EXISTS (SELECT 1 FROM effective_role_assignments r WHERE r.user_id=subject AND r.role=requested_role
                AND (r.department_id IS NULL OR r.department_id=department)
                AND (r.document_id IS NULL OR r.document_id=target_document))));
$$;
CREATE OR REPLACE FUNCTION can_access_version(subject bigint,target_version bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT is_qmb(subject) OR EXISTS (SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id
        WHERE v.id=target_version AND (
            (d.access_mode='DEPARTMENT' AND v.classification IN ('PUBLIC','INTERNAL'))
            OR EXISTS (SELECT 1 FROM document_access_users a WHERE a.document_id=d.id AND a.user_id=subject)
            OR EXISTS (SELECT 1 FROM document_access_groups a JOIN dms_groups g ON g.id=a.group_id AND g.active
                       JOIN group_memberships m ON m.group_id=g.id WHERE a.document_id=d.id AND m.user_id=subject)));
$$;
CREATE OR REPLACE FUNCTION verify_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status='APPROVED' AND OLD.status<>'APPROVED' THEN
        IF NOT EXISTS (
            SELECT 1 FROM workflow_instances w
            JOIN approval_decisions r ON r.workflow_id=w.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
            JOIN approval_decisions a ON a.workflow_id=w.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'
            WHERE w.version_id=NEW.id AND w.closed_at IS NULL
              AND r.version_id=NEW.id AND a.version_id=NEW.id
              AND r.content_fingerprint=w.content_fingerprint AND a.content_fingerprint=w.content_fingerprint
              AND r.actor_id=a.actor_id AND is_qmb(a.actor_id)
              AND r.actor_id<>NEW.created_by AND r.actor_id<>w.submitted_by
              AND r.qmb_role_at_decision IS NOT NULL AND a.qmb_role_at_decision IS NOT NULL
        ) THEN RAISE EXCEPTION 'Review and approval by the same independent active QMB required'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
-- Takeover uses a return to DRAFT followed by a fresh immutable review cycle.
CREATE TABLE storage_locations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE,
    description text NOT NULL DEFAULT '',
    active boolean NOT NULL DEFAULT true
);
INSERT INTO storage_locations(name,description) VALUES ('Zentrale DMS-Ablage','Logischer Aufbewahrungsort. Technischer Dateispeicher wird durch die IT betrieben.');
ALTER TABLE document_categories ADD COLUMN storage_location_id bigint REFERENCES storage_locations(id);
ALTER TABLE document_categories ADD COLUMN retention_months integer CHECK (retention_months BETWEEN 1 AND 1200);
UPDATE document_categories SET storage_location_id=(SELECT id FROM storage_locations ORDER BY id LIMIT 1);
ALTER TABLE document_categories ALTER COLUMN storage_location_id SET NOT NULL;
ALTER TABLE review_notifications ADD COLUMN recipient_kind text NOT NULL DEFAULT 'OWNER' CHECK (recipient_kind IN ('OWNER','QMB'));
ALTER TABLE document_categories ALTER COLUMN storage_location_id SET DEFAULT 1;

-- Reader is explicitly assigned to provisioned DMS accounts; raw/unprovisioned
-- database identities do not gain implicit access. Confidential ACLs still apply.
INSERT INTO role_assignments(user_id,role) SELECT id,'READER' FROM users WHERE auth_user_id IS NOT NULL ON CONFLICT DO NOTHING;
