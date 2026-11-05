BEGIN;

CREATE TABLE departments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    parent_id bigint REFERENCES departments(id),
    CHECK (parent_id IS DISTINCT FROM id)
);

CREATE TABLE users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    display_name text NOT NULL,
    email text,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE external_identities (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES users(id),
    provider text NOT NULL,
    subject text NOT NULL,
    UNIQUE (provider, subject)
);

CREATE TABLE documents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    number text NOT NULL UNIQUE,
    document_type text NOT NULL,
    owner_id bigint NOT NULL REFERENCES users(id),
    responsible_department_id bigint NOT NULL REFERENCES departments(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE file_objects (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    storage_key text NOT NULL UNIQUE,
    original_name text NOT NULL,
    media_type text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE document_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES documents(id),
    major integer NOT NULL CHECK (major >= 0),
    minor integer NOT NULL CHECK (minor >= 0),
    title text NOT NULL CHECK (length(trim(title)) > 0),
    change_summary text NOT NULL,
    created_by bigint NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    status text NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'IN_REVIEW', 'PENDING_APPROVAL', 'APPROVED', 'ARCHIVED')),
    classification text NOT NULL DEFAULT 'INTERNAL'
        CHECK (classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')),
    effective_from timestamptz,
    valid_until timestamptz,
    next_review_on date,
    UNIQUE (document_id, major, minor),
    CHECK (valid_until IS NULL OR (effective_from IS NOT NULL AND valid_until > effective_from)),
    CHECK (status NOT IN ('APPROVED', 'ARCHIVED') OR effective_from IS NOT NULL)
);

CREATE TABLE version_files (
    version_id bigint NOT NULL REFERENCES document_versions(id),
    file_id bigint NOT NULL REFERENCES file_objects(id),
    purpose text NOT NULL CHECK (purpose IN ('ORIGINAL', 'RELEASE', 'ATTACHMENT')),
    PRIMARY KEY (version_id, file_id)
);

CREATE TABLE version_departments (
    version_id bigint NOT NULL REFERENCES document_versions(id),
    department_id bigint NOT NULL REFERENCES departments(id),
    PRIMARY KEY (version_id, department_id)
);

CREATE TABLE standards (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    edition text NOT NULL,
    UNIQUE (name, edition)
);

CREATE TABLE standard_references (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    standard_id bigint NOT NULL REFERENCES standards(id),
    reference text NOT NULL,
    label text NOT NULL,
    UNIQUE (standard_id, reference)
);

CREATE TABLE version_standard_links (
    version_id bigint NOT NULL REFERENCES document_versions(id),
    reference_id bigint NOT NULL REFERENCES standard_references(id),
    PRIMARY KEY (version_id, reference_id)
);

CREATE TABLE approval_decisions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id bigint NOT NULL REFERENCES document_versions(id),
    actor_id bigint NOT NULL REFERENCES users(id),
    stage text NOT NULL CHECK (stage IN ('REVIEW', 'APPROVAL')),
    decision text NOT NULL CHECK (decision IN ('ACCEPT', 'RETURN')),
    comment text NOT NULL DEFAULT '',
    content_fingerprint text NOT NULL CHECK (content_fingerprint ~ '^[0-9a-f]{64}$'),
    decided_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE periodic_reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id bigint NOT NULL REFERENCES document_versions(id),
    reviewer_id bigint NOT NULL REFERENCES users(id),
    result text NOT NULL CHECK (result IN ('UNCHANGED', 'REVISION_REQUIRED', 'WITHDRAWAL_REQUIRED')),
    rationale text NOT NULL CHECK (length(trim(rationale)) > 0),
    next_review_on date,
    reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id bigint REFERENCES users(id),
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text NOT NULL,
    reason text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    correlation_id text,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Released content is immutable; only archival is allowed on the version row.
CREATE FUNCTION guard_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'New versions must start as DRAFT';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Version deletion requires a separate retention procedure';
    END IF;
    IF OLD.status IN ('APPROVED', 'ARCHIVED') THEN
        IF OLD.status = 'APPROVED' AND NEW.status = 'ARCHIVED'
           AND (to_jsonb(NEW) - 'status') = (to_jsonb(OLD) - 'status') THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Released versions are immutable';
    END IF;
    IF OLD.status <> 'DRAFT'
       AND (to_jsonb(NEW) - 'status') <> (to_jsonb(OLD) - 'status') THEN
        RAISE EXCEPTION 'Return version to DRAFT before editing';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'DRAFT' AND NEW.status = 'IN_REVIEW') OR
        (OLD.status = 'IN_REVIEW' AND NEW.status IN ('DRAFT', 'PENDING_APPROVAL')) OR
        (OLD.status = 'PENDING_APPROVAL' AND NEW.status IN ('DRAFT', 'APPROVED'))
    ) THEN
        RAISE EXCEPTION 'Invalid status transition: % -> %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER protect_version BEFORE INSERT OR UPDATE OR DELETE ON document_versions
    FOR EACH ROW EXECUTE FUNCTION guard_version();

-- Lock parent rows to serialize publication and concurrent attachment changes.
CREATE FUNCTION guard_version_link() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_id bigint;
    parent_status text;
BEGIN
    FOR parent_id IN
        SELECT DISTINCT v FROM unnest(ARRAY[
            CASE WHEN TG_OP <> 'INSERT' THEN OLD.version_id END,
            CASE WHEN TG_OP <> 'DELETE' THEN NEW.version_id END
        ]) v WHERE v IS NOT NULL ORDER BY v
    LOOP
        SELECT status INTO parent_status FROM document_versions WHERE id = parent_id FOR UPDATE;
        IF parent_status IS DISTINCT FROM 'DRAFT' THEN
            RAISE EXCEPTION 'Version associations can only change in DRAFT';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER protect_files BEFORE INSERT OR UPDATE OR DELETE ON version_files
    FOR EACH ROW EXECUTE FUNCTION guard_version_link();
CREATE TRIGGER protect_departments BEFORE INSERT OR UPDATE OR DELETE ON version_departments
    FOR EACH ROW EXECUTE FUNCTION guard_version_link();
CREATE TRIGGER protect_standard_links BEFORE INSERT OR UPDATE OR DELETE ON version_standard_links
    FOR EACH ROW EXECUTE FUNCTION guard_version_link();

CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER immutable_files BEFORE UPDATE OR DELETE ON file_objects
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_decisions BEFORE UPDATE OR DELETE ON approval_decisions
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_reviews BEFORE UPDATE OR DELETE ON periodic_reviews
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE INDEX versions_document_status ON document_versions(document_id, status);
CREATE INDEX versions_review_due ON document_versions(next_review_on) WHERE status = 'APPROVED';
CREATE INDEX version_departments_department ON version_departments(department_id);
CREATE INDEX version_standards_reference ON version_standard_links(reference_id);
CREATE INDEX decisions_version ON approval_decisions(version_id);
CREATE INDEX reviews_version ON periodic_reviews(version_id, reviewed_at);
CREATE INDEX audit_object ON audit_events(object_type, object_id, occurred_at);

COMMIT;
