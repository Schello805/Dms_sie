-- QMBs can create documents and work on their own documents, without author access to other drafts.
CREATE OR REPLACE FUNCTION has_role(subject bigint,requested_role text,department bigint,target_document bigint DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id
        WHERE u.id=subject AND u.active AND a.is_active AND (
            (requested_role='REVIEWER' AND is_qmb(subject))
            OR (requested_role='AUTHOR' AND is_qmb(subject) AND (
                target_document IS NULL OR EXISTS(SELECT 1 FROM documents d WHERE d.id=target_document
                    AND (d.owner_id=subject OR EXISTS(SELECT 1 FROM document_versions v WHERE v.document_id=d.id AND v.created_by=subject)))))
            OR (requested_role='ADMIN' AND u.settings_admin)
            OR EXISTS (SELECT 1 FROM effective_role_assignments r WHERE r.user_id=subject AND r.role=requested_role
                AND (r.department_id IS NULL OR r.department_id=department)
                AND (r.document_id IS NULL OR r.document_id=target_document))));
$$;
