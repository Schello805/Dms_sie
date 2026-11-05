CREATE TABLE document_withdrawals (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES documents(id),
    actor_id bigint NOT NULL REFERENCES users(id),
    reason text NOT NULL CHECK (length(trim(reason))>0),
    withdrawn_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX withdrawals_document ON document_withdrawals(document_id,withdrawn_at DESC);
CREATE TRIGGER immutable_withdrawals BEFORE UPDATE OR DELETE ON document_withdrawals
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- Archived releases remain in the selection as tombstones; never fall back.
-- A withdrawal also cancels already approved future publications. Only a new
-- approval after the withdrawal can restore availability at its effective date.
CREATE OR REPLACE FUNCTION current_release(target_document bigint) RETURNS bigint
LANGUAGE sql STABLE AS $$
    WITH latest AS (
        SELECT v.id,v.status FROM document_versions v
        WHERE v.document_id=target_document AND v.status IN ('APPROVED','ARCHIVED')
          AND v.effective_from<=now()
          AND NOT EXISTS (
              SELECT 1 FROM document_withdrawals w WHERE w.document_id=v.document_id
              AND w.withdrawn_at>=COALESCE((SELECT max(a.decided_at) FROM approval_decisions a
                  WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'),v.created_at)
          )
        ORDER BY v.effective_from DESC,v.major DESC,v.minor DESC LIMIT 1
    ) SELECT id FROM latest WHERE status='APPROVED';
$$;
