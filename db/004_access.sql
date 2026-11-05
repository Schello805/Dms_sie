CREATE TABLE dms_groups (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE,
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE group_memberships (
    group_id bigint NOT NULL REFERENCES dms_groups(id),
    user_id bigint NOT NULL REFERENCES users(id),
    PRIMARY KEY (group_id,user_id)
);
CREATE INDEX memberships_user ON group_memberships(user_id);
ALTER TABLE role_assignments ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE role_assignments ADD COLUMN group_id bigint REFERENCES dms_groups(id);
ALTER TABLE role_assignments ADD COLUMN document_id bigint REFERENCES documents(id);
ALTER TABLE role_assignments DROP CONSTRAINT role_assignments_user_id_role_department_id_key;
ALTER TABLE role_assignments ADD CONSTRAINT exactly_one_role_subject CHECK ((user_id IS NOT NULL) <> (group_id IS NOT NULL));
ALTER TABLE role_assignments ADD CONSTRAINT one_role_scope CHECK (department_id IS NULL OR document_id IS NULL);
ALTER TABLE role_assignments ADD CONSTRAINT unique_role_assignment UNIQUE NULLS NOT DISTINCT (user_id,group_id,role,department_id,document_id);
ALTER TABLE documents ADD COLUMN access_mode text NOT NULL DEFAULT 'DEPARTMENT' CHECK (access_mode IN ('DEPARTMENT','EXPLICIT'));
CREATE TABLE document_access_users (
    document_id bigint NOT NULL REFERENCES documents(id),
    user_id bigint NOT NULL REFERENCES users(id),
    PRIMARY KEY(document_id,user_id)
);
CREATE TABLE document_access_groups (
    document_id bigint NOT NULL REFERENCES documents(id),
    group_id bigint NOT NULL REFERENCES dms_groups(id),
    PRIMARY KEY(document_id,group_id)
);
-- Existing authors retain explicit eligibility if a draft is classified later.
INSERT INTO document_access_users(document_id,user_id) SELECT id,owner_id FROM documents;
CREATE VIEW effective_role_assignments AS
    SELECT user_id,role,department_id,document_id FROM role_assignments WHERE user_id IS NOT NULL
    UNION ALL
    SELECT m.user_id,r.role,r.department_id,r.document_id FROM role_assignments r
    JOIN dms_groups g ON g.id=r.group_id AND g.active
    JOIN group_memberships m ON m.group_id=g.id;

CREATE FUNCTION has_role(subject bigint, requested_role text, department bigint, target_document bigint DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM effective_role_assignments r
        JOIN users u ON u.id=r.user_id AND u.active
        JOIN auth_user a ON a.id=u.auth_user_id AND a.is_active
        WHERE r.user_id=subject AND r.role=requested_role
          AND (r.department_id IS NULL OR r.department_id=department)
          AND (r.document_id IS NULL OR r.document_id=target_document));
$$;
CREATE FUNCTION can_access_version(subject bigint,target_version bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id
        WHERE v.id=target_version AND (
            (d.access_mode='DEPARTMENT' AND v.classification IN ('PUBLIC','INTERNAL'))
            OR EXISTS (SELECT 1 FROM document_access_users a WHERE a.document_id=d.id AND a.user_id=subject)
            OR EXISTS (SELECT 1 FROM document_access_groups a JOIN dms_groups g ON g.id=a.group_id AND g.active
                       JOIN group_memberships m ON m.group_id=g.id WHERE a.document_id=d.id AND m.user_id=subject)));
$$;
CREATE FUNCTION can_read_version(subject bigint,target_version bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id
        WHERE v.id=target_version AND can_access_version(subject,v.id) AND (
            has_role(subject,'AUTHOR',d.responsible_department_id,d.id)
            OR has_role(subject,'REVIEWER',d.responsible_department_id,d.id)
            OR has_role(subject,'APPROVER',d.responsible_department_id,d.id)
            OR (has_role(subject,'READER',d.responsible_department_id,d.id)
                AND v.id=current_release(d.id) AND v.status='APPROVED'
                AND (v.valid_until IS NULL OR v.valid_until>now()))));
$$;
