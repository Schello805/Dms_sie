CREATE TABLE audience_groups (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 name text NOT NULL UNIQUE CHECK (length(trim(name)) BETWEEN 1 AND 200),
 description text NOT NULL DEFAULT '', active boolean NOT NULL DEFAULT true
);
CREATE TABLE audience_memberships (
 user_id bigint NOT NULL REFERENCES users(id), audience_id bigint NOT NULL REFERENCES audience_groups(id),
 PRIMARY KEY(user_id,audience_id)
);
CREATE TABLE user_workplaces (
 user_id bigint PRIMARY KEY REFERENCES users(id), department_id bigint REFERENCES departments(id),
 site text NOT NULL DEFAULT '', activity text NOT NULL DEFAULT ''
);
CREATE TABLE version_distribution (
 version_id bigint PRIMARY KEY REFERENCES document_versions(id),
 change_kind text NOT NULL DEFAULT 'SUBSTANTIAL' CHECK(change_kind IN ('EDITORIAL','SUBSTANTIAL')),
 requires_ack boolean NOT NULL DEFAULT false,
 ack_days integer NOT NULL DEFAULT 30 CHECK(ack_days BETWEEN 1 AND 3650),
 keywords text NOT NULL DEFAULT '' CHECK(length(keywords)<=2000)
);
CREATE TABLE version_audiences (
 version_id bigint NOT NULL REFERENCES document_versions(id), audience_id bigint NOT NULL REFERENCES audience_groups(id),
 PRIMARY KEY(version_id,audience_id)
);
CREATE TRIGGER protect_distribution BEFORE INSERT OR UPDATE OR DELETE ON version_distribution
 FOR EACH ROW EXECUTE FUNCTION guard_version_link();
CREATE TRIGGER protect_audiences BEFORE INSERT OR UPDATE OR DELETE ON version_audiences
 FOR EACH ROW EXECUTE FUNCTION guard_version_link();
CREATE TABLE document_bookmarks (
 user_id bigint NOT NULL REFERENCES users(id), document_id bigint NOT NULL REFERENCES documents(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(user_id,document_id)
);
CREATE TABLE acknowledgement_assignments (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 version_id bigint NOT NULL REFERENCES document_versions(id), user_id bigint NOT NULL REFERENCES users(id),
 assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(), due_on date NOT NULL,
 UNIQUE(version_id,user_id)
);
CREATE TABLE acknowledgement_receipts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 assignment_id bigint NOT NULL UNIQUE REFERENCES acknowledgement_assignments(id),
 acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 content_fingerprint text NOT NULL CHECK(content_fingerprint ~ '^[0-9a-f]{64}$')
);
CREATE TRIGGER immutable_ack_assignments BEFORE UPDATE OR DELETE ON acknowledgement_assignments
 FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_ack_receipts BEFORE UPDATE OR DELETE ON acknowledgement_receipts
 FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TABLE evidence_records (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 number text NOT NULL UNIQUE CHECK(length(trim(number)) BETWEEN 1 AND 100),
 title text NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 400),
 category_id bigint NOT NULL REFERENCES document_categories(id),
 department_id bigint NOT NULL REFERENCES departments(id), owner_id bigint NOT NULL REFERENCES users(id),
 source_version_id bigint REFERENCES document_versions(id),
 occurred_on date NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 retain_until date NOT NULL, classification text NOT NULL DEFAULT 'INTERNAL'
 CHECK(classification IN ('INTERNAL','CONFIDENTIAL','RESTRICTED')),
 file_id bigint NOT NULL REFERENCES file_objects(id), reason text NOT NULL CHECK(length(trim(reason))>0),
 CHECK(retain_until>=occurred_on)
);
CREATE TABLE evidence_retention_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 record_id bigint NOT NULL REFERENCES evidence_records(id), actor_id bigint NOT NULL REFERENCES users(id),
 retain_until date NOT NULL, legal_hold boolean NOT NULL,
 reason text NOT NULL CHECK(length(trim(reason))>0), created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE evidence_disposal_requests (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 record_id bigint NOT NULL REFERENCES evidence_records(id), actor_id bigint NOT NULL REFERENCES users(id),
 reason text NOT NULL CHECK(length(trim(reason))>0), created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON evidence_records FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_retention BEFORE UPDATE OR DELETE ON evidence_retention_events FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_disposal BEFORE UPDATE OR DELETE ON evidence_disposal_requests FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE FUNCTION can_read_evidence(subject bigint,target_record bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT is_qmb(subject) OR EXISTS (
 SELECT 1 FROM evidence_records r WHERE r.id=target_record AND (
 (r.owner_id=subject AND EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=subject AND u.active AND a.is_active))
 OR (r.classification='INTERNAL' AND (has_role(subject,'READER',r.department_id,NULL)
 OR has_role(subject,'AUTHOR',r.department_id,NULL) OR has_role(subject,'REVIEWER',r.department_id,NULL)))));
$$;
CREATE INDEX acknowledgement_user ON acknowledgement_assignments(user_id,version_id);
CREATE INDEX evidence_department ON evidence_records(department_id,occurred_on);
CREATE INDEX audience_member_group ON audience_memberships(audience_id,user_id);
CREATE FUNCTION validate_evidence_retention() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE minimum_date date;
BEGIN
 IF NOT is_qmb(NEW.actor_id) THEN RAISE EXCEPTION 'Retention decision requires active QMB'; END IF;
 SELECT retain_until INTO minimum_date FROM evidence_records WHERE id=NEW.record_id FOR UPDATE;
 SELECT greatest(minimum_date,COALESCE(max(retain_until),minimum_date)) INTO minimum_date
 FROM evidence_retention_events WHERE record_id=NEW.record_id;
 IF NEW.retain_until<minimum_date THEN RAISE EXCEPTION 'Retention cannot be shortened'; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER validate_retention BEFORE INSERT ON evidence_retention_events
 FOR EACH ROW EXECUTE FUNCTION validate_evidence_retention();
