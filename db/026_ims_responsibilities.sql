-- Operational responsibility is separate from immutable version authorship.
ALTER TABLE documents ADD COLUMN login_required boolean NOT NULL DEFAULT false;
CREATE FUNCTION transfer_document_owner(actor bigint,target bigint,previous bigint,successor bigint,why text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE doc public.documents;
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 SELECT * INTO STRICT doc FROM public.documents WHERE id=target FOR UPDATE;
 PERFORM pg_advisory_xact_lock(doc.id);
 IF doc.owner_id<>previous THEN RAISE EXCEPTION 'Responsibility changed; reload first'; END IF;
 IF previous=successor THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.auth_user a ON a.id=u.auth_user_id
   WHERE u.id=successor AND u.active AND a.is_active AND (public.is_qmb(u.id) OR public.has_role(u.id,'AUTHOR',doc.responsible_department_id,doc.id))) THEN
  RAISE EXCEPTION 'Active author for this department/document required'; END IF;
 UPDATE public.documents SET owner_id=successor WHERE id=target;
 INSERT INTO public.document_access_users(document_id,user_id) VALUES(target,successor) ON CONFLICT DO NOTHING;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
 VALUES(actor,'TRANSFER_RESPONSIBILITY','document',target::text,coalesce(nullif(btrim(why),''),'Keine zusätzliche Begründung angegeben.'),
  jsonb_build_object('before',previous,'after',successor,'historical_authorship_preserved',true));
END;
$$;
CREATE FUNCTION set_document_login_required(actor bigint,target bigint,required boolean,why text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE previous boolean;
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 SELECT login_required INTO STRICT previous FROM public.documents WHERE id=target FOR UPDATE;
 IF previous IS DISTINCT FROM required THEN
  UPDATE public.documents SET login_required=required WHERE id=target;
  INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
  VALUES(actor,'CHANGE_READING_ACCESS','document',target::text,coalesce(nullif(btrim(why),''),'Keine zusätzliche Begründung angegeben.'),
   jsonb_build_object('before_login_required',previous,'after_login_required',required));
 END IF;
END;
$$;
REVOKE ALL ON FUNCTION transfer_document_owner(bigint,bigint,bigint,bigint,text),set_document_login_required(bigint,bigint,boolean,text) FROM PUBLIC;
