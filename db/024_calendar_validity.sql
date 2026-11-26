-- Calendar-day validity without rewriting frozen versions or audit timestamps.
CREATE OR REPLACE FUNCTION current_release(target_document bigint) RETURNS bigint LANGUAGE sql STABLE AS $$
 WITH latest AS (
 SELECT v.id,v.status FROM document_versions v WHERE v.document_id=target_document AND EXISTS(SELECT 1 FROM documents doc WHERE doc.id=target_document AND doc.active)
 AND v.status IN ('APPROVED','ARCHIVED') AND (v.effective_from AT TIME ZONE 'Europe/Berlin')::date<=(statement_timestamp() AT TIME ZONE 'Europe/Berlin')::date
 AND NOT EXISTS(SELECT 1 FROM document_withdrawals w WHERE w.document_id=v.document_id
 AND w.withdrawn_at>=COALESCE((SELECT max(a.decided_at) FROM approval_decisions a
 WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'),v.created_at))
 ORDER BY (v.effective_from AT TIME ZONE 'Europe/Berlin')::date DESC,v.major DESC,v.minor DESC LIMIT 1
 ) SELECT id FROM latest WHERE status='APPROVED';
$$;
