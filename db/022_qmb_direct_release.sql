CREATE TABLE qmb_direct_releases (
 version_id bigint PRIMARY KEY REFERENCES document_versions(id),
 actor_id bigint NOT NULL REFERENCES users(id),
 content_fingerprint text NOT NULL CHECK(length(content_fingerprint)=64),
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER immutable_qmb_direct_release BEFORE UPDATE OR DELETE ON qmb_direct_releases FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE OR REPLACE FUNCTION verify_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status='APPROVED' AND OLD.status<>'APPROVED' THEN
 IF NOT EXISTS(SELECT 1 FROM workflow_instances w
 JOIN approval_decisions r ON r.workflow_id=w.id AND r.stage='REVIEW' AND r.decision='ACCEPT'
 JOIN approval_decisions a ON a.workflow_id=w.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'
 WHERE w.version_id=NEW.id AND w.closed_at IS NULL AND r.version_id=NEW.id AND a.version_id=NEW.id
 AND r.content_fingerprint=w.content_fingerprint AND a.content_fingerprint=w.content_fingerprint
 AND r.actor_id=a.actor_id AND is_qmb(a.actor_id)
 AND r.qmb_role_at_decision IS NOT NULL AND a.qmb_role_at_decision IS NOT NULL
 AND ((r.actor_id<>NEW.created_by AND r.actor_id<>w.submitted_by) OR EXISTS(
  SELECT 1 FROM qmb_direct_releases d WHERE d.version_id=NEW.id AND d.actor_id=NEW.created_by
  AND d.actor_id=a.actor_id AND w.submitted_by=d.actor_id AND d.content_fingerprint=w.content_fingerprint)))
 THEN RAISE EXCEPTION 'Active QMB decision or recorded QMB author release required'; END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE FUNCTION release_qmb_document(actor bigint,target bigint,digest text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE v public.document_versions; cycle bigint; approved timestamptz; months integer; qualification text;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtext('ims-user-roles'));
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'Active QMB required'; END IF;
 SELECT * INTO STRICT v FROM public.document_versions WHERE id=target FOR UPDATE;
 IF v.created_by<>actor OR v.status<>'DRAFT' OR NOT v.approval_based_validity OR digest !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'Own completed QMB draft required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.version_files WHERE version_id=target) OR v.effective_from IS NULL THEN RAISE EXCEPTION 'File and effective date required'; END IF;
 PERFORM pg_advisory_xact_lock(v.document_id);
 SELECT c.review_interval_months INTO STRICT months FROM public.documents d JOIN public.document_categories c ON c.name=d.document_type WHERE d.id=v.document_id FOR SHARE OF c;
 SELECT qmb_role INTO qualification FROM public.users WHERE id=actor;
 INSERT INTO public.workflow_instances(version_id,content_fingerprint,submitted_by) VALUES(target,digest,actor) RETURNING id INTO cycle;
 UPDATE public.document_versions SET status='IN_REVIEW' WHERE id=target;
 INSERT INTO public.approval_decisions(version_id,actor_id,stage,decision,comment,content_fingerprint,workflow_id,qmb_role_at_decision)
 VALUES(target,actor,'REVIEW','ACCEPT','Direktfreigabe durch verantwortlichen QMB',digest,cycle,qualification);
 UPDATE public.document_versions SET status='PENDING_APPROVAL' WHERE id=target;
 INSERT INTO public.approval_decisions(version_id,actor_id,stage,decision,comment,content_fingerprint,workflow_id,qmb_role_at_decision)
 VALUES(target,actor,'APPROVAL','ACCEPT','Direktfreigabe durch verantwortlichen QMB',digest,cycle,qualification) RETURNING decided_at INTO approved;
 INSERT INTO public.qmb_direct_releases(version_id,actor_id,content_fingerprint,approved_at) VALUES(target,actor,digest,approved);
 INSERT INTO public.release_validity(version_id,approved_at,review_due_on,interval_months)
 VALUES(target,approved,((approved AT TIME ZONE 'Europe/Berlin')::date+make_interval(months=>months))::date,months);
 UPDATE public.document_versions SET status='APPROVED' WHERE id=target;
 UPDATE public.workflow_instances SET closed_at=clock_timestamp() WHERE id=cycle;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
 VALUES(actor,'QMB_DIRECT_RELEASE','version',target::text,'Direktfreigabe: Autor ist aktiver QMB',jsonb_build_object('fingerprint',digest,'qmb_role',qualification,'interval_months',months));
END;
$$;
REVOKE ALL ON FUNCTION release_qmb_document(bigint,bigint,text) FROM PUBLIC;
