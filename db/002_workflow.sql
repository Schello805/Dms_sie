ALTER TABLE users ADD COLUMN auth_user_id integer UNIQUE REFERENCES auth_user(id);
CREATE TABLE role_assignments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES users(id),
    role text NOT NULL CHECK (role IN ('READER','AUTHOR','REVIEWER','APPROVER')),
    department_id bigint REFERENCES departments(id),
    UNIQUE NULLS NOT DISTINCT (user_id, role, department_id)
);
CREATE TABLE workflow_instances (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id bigint NOT NULL REFERENCES document_versions(id),
    content_fingerprint text NOT NULL CHECK (content_fingerprint ~ '^[0-9a-f]{64}$'),
    submitted_by bigint NOT NULL REFERENCES users(id),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    closed_at timestamptz
);
CREATE UNIQUE INDEX one_open_workflow ON workflow_instances(version_id) WHERE closed_at IS NULL;
ALTER TABLE approval_decisions ADD COLUMN workflow_id bigint NOT NULL REFERENCES workflow_instances(id);
CREATE UNIQUE INDEX one_stage_decision ON approval_decisions(workflow_id, stage);

-- Publication requires a matching, independent review and approval in the current cycle.
CREATE FUNCTION verify_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'APPROVED' AND OLD.status <> 'APPROVED' THEN
        IF NOT EXISTS (
            SELECT 1 FROM workflow_instances w
            JOIN approval_decisions r ON r.workflow_id=w.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
            JOIN approval_decisions a ON a.workflow_id=w.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'
            WHERE w.version_id=NEW.id AND w.closed_at IS NULL
              AND r.version_id=NEW.id AND a.version_id=NEW.id
              AND r.content_fingerprint=w.content_fingerprint AND a.content_fingerprint=w.content_fingerprint
              AND r.actor_id<>a.actor_id AND r.actor_id<>NEW.created_by
              AND a.actor_id<>NEW.created_by AND a.actor_id<>w.submitted_by
              AND r.actor_id<>w.submitted_by
        ) THEN
            RAISE EXCEPTION 'Independent review and approval required';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER verify_release BEFORE UPDATE ON document_versions
    FOR EACH ROW EXECUTE FUNCTION verify_publication();

-- Latest effective release wins. An expired successor does not revive an old release.
CREATE FUNCTION current_release(target_document bigint) RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT id FROM document_versions
    WHERE document_id=target_document AND status='APPROVED' AND effective_from<=now()
    ORDER BY effective_from DESC, major DESC, minor DESC LIMIT 1;
$$;
