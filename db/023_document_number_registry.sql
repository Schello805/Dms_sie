ALTER TABLE document_categories ADD COLUMN number_prefix text NOT NULL DEFAULT 'DOK' CHECK(number_prefix ~ '^[A-Z][A-Z0-9]{0,11}$');
UPDATE document_categories SET number_prefix=CASE name WHEN 'Prozess' THEN 'PB' WHEN 'Arbeitsanweisung' THEN 'AA' WHEN 'Richtlinie' THEN 'RL' WHEN 'Vorlage' THEN 'VL' WHEN 'Externe Norm' THEN 'N' WHEN 'Betriebsanweisung' THEN 'BA' WHEN 'SOP' THEN 'SOP' ELSE CASE WHEN display_name='Handbücher' THEN 'HB' ELSE 'DOK' END END;
ALTER TABLE documents ADD COLUMN active boolean NOT NULL DEFAULT true;
CREATE SEQUENCE document_number_sequence;
-- Start beyond every known legacy numeric suffix; old numbers are not rewritten.
SELECT setval('document_number_sequence',greatest(1,coalesce((SELECT max(((regexp_match(number,'([0-9]{1,15})$'))[1])::bigint) FROM documents),0)+1),false);
CREATE TABLE document_number_registry (
 number text PRIMARY KEY,document_id bigint NOT NULL UNIQUE REFERENCES documents(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX document_number_registry_normalized ON document_number_registry(lower(btrim(number)));
INSERT INTO document_number_registry(number,document_id,created_at) SELECT number,id,created_at FROM documents;
CREATE TRIGGER immutable_number_registry BEFORE UPDATE OR DELETE ON document_number_registry FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE FUNCTION guard_document_number() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Deactivate documents; issued numbers are permanent'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (NEW.number,NEW.document_type) IS DISTINCT FROM (OLD.number,OLD.document_type) THEN RAISE EXCEPTION 'Issued document number and type are immutable'; END IF;
 ELSE
  PERFORM pg_advisory_xact_lock(hashtext('ims-issued-numbers'));
  NEW.number:=btrim(NEW.number);
  IF EXISTS(SELECT 1 FROM public.document_number_registry WHERE lower(btrim(number))=lower(NEW.number)) THEN
   RAISE EXCEPTION 'Document number already issued' USING ERRCODE='23505'; END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER protect_document_number BEFORE INSERT OR UPDATE OF number,document_type OR DELETE ON documents FOR EACH ROW EXECUTE FUNCTION guard_document_number();
CREATE FUNCTION record_document_number() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 INSERT INTO public.document_number_registry(number,document_id) VALUES(NEW.number,NEW.id);
 RETURN NEW;
END;
$$;
CREATE TRIGGER record_issued_number AFTER INSERT ON documents FOR EACH ROW EXECUTE FUNCTION record_document_number();
CREATE FUNCTION allocate_document_number(actor bigint,kind text) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE prefix text;serial bigint;candidate text;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active AND
 (public.is_qmb(actor) OR EXISTS(SELECT 1 FROM public.effective_role_assignments r WHERE r.user_id=actor AND r.role='AUTHOR' AND r.document_id IS NULL))) THEN RAISE EXCEPTION 'Active author or QMB required'; END IF;
 SELECT number_prefix INTO STRICT prefix FROM public.document_categories WHERE name=kind AND active;
 PERFORM pg_advisory_xact_lock(hashtext('ims-issued-numbers'));
 LOOP
  serial:=nextval('public.document_number_sequence');
  candidate:=prefix||'-'||lpad(serial::text,greatest(4,length(serial::text)),'0');
  IF NOT EXISTS(SELECT 1 FROM public.document_number_registry WHERE lower(btrim(number))=lower(candidate)) THEN RETURN candidate; END IF;
 END LOOP;
END;
$$;
CREATE FUNCTION set_category_number_prefix(actor bigint,target bigint,prefix text,why text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE previous text;desired text;
BEGIN
 PERFORM public.require_ims_manager(actor,false);
 PERFORM pg_advisory_xact_lock(hashtext('ims-master-data'));
 SELECT number_prefix INTO STRICT previous FROM public.document_categories WHERE id=target FOR UPDATE;
 desired:=coalesce(nullif(upper(btrim(prefix)),''),previous);
 IF desired !~ '^[A-Z][A-Z0-9]{0,11}$' THEN RAISE EXCEPTION 'Invalid document number prefix'; END IF;
 IF previous<>desired THEN
  UPDATE public.document_categories SET number_prefix=desired WHERE id=target;
  INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
  VALUES(actor,'CHANGE_NUMBER_PREFIX','category',target::text,coalesce(nullif(btrim(why),''),'Keine zusätzliche Begründung angegeben.'),jsonb_build_object('before',previous,'after',desired));
 END IF;
END;
$$;
CREATE FUNCTION set_document_active(actor bigint,target bigint,enabled boolean) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE previous boolean;
BEGIN
 PERFORM public.require_ims_manager(actor,false);
 SELECT active INTO STRICT previous FROM public.documents WHERE id=target FOR UPDATE;
 UPDATE public.documents SET active=enabled WHERE id=target;
 IF previous<>enabled THEN INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
 VALUES(actor,'SET_DOCUMENT_ACTIVE','document',target::text,'Dokumentenstatus durch QMB geändert',jsonb_build_object('before',previous,'active',enabled)); END IF;
END;
$$;
REVOKE ALL ON FUNCTION guard_document_number(),record_document_number(),allocate_document_number(bigint,text),set_category_number_prefix(bigint,bigint,text,text),set_document_active(bigint,bigint,boolean) FROM PUBLIC;

CREATE OR REPLACE FUNCTION current_release(target_document bigint) RETURNS bigint LANGUAGE sql STABLE AS $$
 WITH latest AS (
 SELECT v.id,v.status FROM document_versions v WHERE v.document_id=target_document AND EXISTS(SELECT 1 FROM documents doc WHERE doc.id=target_document AND doc.active)
 AND v.status IN ('APPROVED','ARCHIVED') AND v.effective_from<=statement_timestamp()
 AND NOT EXISTS(SELECT 1 FROM document_withdrawals w WHERE w.document_id=v.document_id
 AND w.withdrawn_at>=COALESCE((SELECT max(a.decided_at) FROM approval_decisions a
 WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT'),v.created_at))
 ORDER BY v.effective_from DESC,v.major DESC,v.minor DESC LIMIT 1
 ) SELECT id FROM latest WHERE status='APPROVED';
$$;
CREATE OR REPLACE FUNCTION can_read_version(subject bigint,target_version bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM documents doc JOIN document_versions ver ON ver.document_id=doc.id WHERE ver.id=target_version AND (doc.active OR is_qmb(subject))) AND (can_lead_approve(subject,target_version) OR EXISTS (
 SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id
 WHERE v.id=target_version AND can_access_version(subject,v.id) AND (
 has_role(subject,'AUTHOR',d.responsible_department_id,d.id)
 OR has_role(subject,'REVIEWER',d.responsible_department_id,d.id)
 OR (has_role(subject,'READER',d.responsible_department_id,d.id) AND v.id=current_release(d.id) AND v.status='APPROVED'))));
$$;
