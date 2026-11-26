ALTER TABLE document_number_registry DROP CONSTRAINT document_number_registry_document_id_key;
CREATE INDEX document_number_registry_document ON document_number_registry(document_id);
CREATE OR REPLACE FUNCTION guard_document_number() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Deactivate documents; issued numbers are permanent'; END IF;
 IF TG_OP='UPDATE' AND NEW.document_type IS DISTINCT FROM OLD.document_type THEN RAISE EXCEPTION 'Document type is immutable'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ims-issued-numbers'));
 NEW.number:=btrim(NEW.number);
 IF coalesce(length(NEW.number),0)=0 OR length(NEW.number)>100 THEN RAISE EXCEPTION 'Document number required'; END IF;
 IF EXISTS(SELECT 1 FROM public.document_number_registry r WHERE lower(btrim(r.number))=lower(NEW.number)
   AND (TG_OP='INSERT' OR r.document_id<>NEW.id)) THEN
  RAISE EXCEPTION 'Document number already issued' USING ERRCODE='23505';
 END IF;
 RETURN NEW;
END;
$$;
CREATE OR REPLACE FUNCTION record_document_number() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 INSERT INTO public.document_number_registry(number,document_id) VALUES(NEW.number,NEW.id) ON CONFLICT(number) DO NOTHING;
 RETURN NEW;
END;
$$;
CREATE TRIGGER record_changed_number AFTER UPDATE OF number ON documents FOR EACH ROW EXECUTE FUNCTION record_document_number();
CREATE FUNCTION rename_document(actor bigint,target bigint,desired text,why text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE doc public.documents;
BEGIN
 SELECT * INTO STRICT doc FROM public.documents WHERE id=target FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.auth_user a ON a.id=u.auth_user_id
  WHERE u.id=actor AND u.active AND a.is_active AND
   (public.is_qmb(actor) OR (doc.owner_id=actor AND public.has_role(actor,'AUTHOR',doc.responsible_department_id,doc.id)))) THEN
  RAISE EXCEPTION 'Owner author or QMB required'; END IF;
 IF NOT doc.active THEN RAISE EXCEPTION 'Reactivate document first'; END IF;
 desired:=btrim(desired);
 IF doc.number IS DISTINCT FROM desired THEN
  UPDATE public.documents SET number=desired WHERE id=target;
  INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
  VALUES(actor,'RENAME_DOCUMENT','document',target::text,coalesce(nullif(btrim(why),''),'Keine zusätzliche Begründung angegeben.'),
   jsonb_build_object('before',doc.number,'after',desired));
 END IF;
END;
$$;
REVOKE ALL ON FUNCTION rename_document(bigint,bigint,text,text) FROM PUBLIC;
