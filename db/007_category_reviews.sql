CREATE TABLE document_categories (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE,
    review_interval_months integer NOT NULL DEFAULT 24 CHECK (review_interval_months BETWEEN 1 AND 1200),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO document_categories(name) VALUES
    ('Richtlinie'),('Prozess'),('Arbeitsanweisung'),('Betriebsanweisung'),('Vorlage'),('Externe Norm');
INSERT INTO document_categories(name) SELECT DISTINCT document_type FROM documents ON CONFLICT DO NOTHING;
ALTER TABLE documents ADD CONSTRAINT document_category_fk FOREIGN KEY(document_type) REFERENCES document_categories(name);
ALTER TABLE users ADD COLUMN settings_admin boolean NOT NULL DEFAULT false;
ALTER TABLE periodic_reviews ADD COLUMN review_interval_months integer CHECK (review_interval_months BETWEEN 1 AND 1200);
CREATE VIEW version_review_status AS
SELECT v.id AS version_id,
    COALESCE(success.next_review_on,v.next_review_on) AS review_due_on,
    (COALESCE(latest.reviewed_at,initial_review.reviewed_at) AT TIME ZONE 'Europe/Berlin')::date AS last_review_on,
    latest.result AS review_result
FROM document_versions v
LEFT JOIN LATERAL (SELECT reviewed_at,result FROM periodic_reviews pr
    WHERE pr.version_id=v.id ORDER BY pr.id DESC LIMIT 1) latest ON true
LEFT JOIN LATERAL (SELECT next_review_on FROM periodic_reviews pr
    WHERE pr.version_id=v.id AND pr.result='UNCHANGED' ORDER BY pr.id DESC LIMIT 1) success ON true
LEFT JOIN LATERAL (SELECT max(r.decided_at) AS reviewed_at FROM approval_decisions r
    WHERE r.version_id=v.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
      AND EXISTS (SELECT 1 FROM approval_decisions a WHERE a.workflow_id=r.workflow_id
                  AND a.stage='APPROVAL' AND a.decision='ACCEPT')) initial_review ON true;
