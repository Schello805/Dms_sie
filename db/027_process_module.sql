CREATE TABLE ims_processes (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 parent_id bigint REFERENCES ims_processes(id),
 level smallint NOT NULL CHECK(level BETWEEN 1 AND 4),
 code text NOT NULL UNIQUE CHECK(length(btrim(code)) BETWEEN 1 AND 80),
 draft jsonb NOT NULL,
 live jsonb,
 revision integer NOT NULL DEFAULT 0,
 active boolean NOT NULL DEFAULT true,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((level=1)=(parent_id IS NULL))
);
CREATE UNIQUE INDEX ims_process_code_unique ON ims_processes(lower(btrim(code)));
CREATE INDEX ims_process_parent ON ims_processes(parent_id);
CREATE TABLE ims_process_revisions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 process_id bigint NOT NULL REFERENCES ims_processes(id),
 revision integer NOT NULL,
 payload jsonb NOT NULL,
 actor_id bigint NOT NULL REFERENCES users(id),
 released_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(process_id,revision)
);
CREATE FUNCTION guard_process_tree() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Deactivate processes instead'; END IF;
 IF TG_OP='UPDATE' AND (NEW.parent_id IS DISTINCT FROM OLD.parent_id OR NEW.level<>OLD.level OR NEW.code<>OLD.code) THEN
  RAISE EXCEPTION 'Process identity and hierarchy are immutable'; END IF;
 IF NEW.parent_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ims_processes WHERE id=NEW.parent_id AND level=NEW.level-1) THEN
  RAISE EXCEPTION 'Parent must be exactly one level above'; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER process_tree_guard BEFORE INSERT OR UPDATE OR DELETE ON ims_processes FOR EACH ROW EXECUTE FUNCTION guard_process_tree();
CREATE FUNCTION guard_process_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Process releases are append-only'; END;
$$;
CREATE TRIGGER process_revision_guard BEFORE UPDATE OR DELETE ON ims_process_revisions FOR EACH ROW EXECUTE FUNCTION guard_process_revision();
CREATE FUNCTION save_ims_process(actor bigint,target bigint,parent bigint,identifier text,payload jsonb,publish boolean,enabled boolean,why text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE node public.ims_processes; parent_node public.ims_processes; previous jsonb;
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ims-process-tree'));
 IF jsonb_typeof(payload)<>'object' OR coalesce(length(btrim(payload->>'title')),0)=0 OR length(payload->>'title')>300 THEN RAISE EXCEPTION 'Title required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.auth_user a ON a.id=u.auth_user_id WHERE u.id=(payload->>'owner_id')::bigint AND u.active AND a.is_active) THEN RAISE EXCEPTION 'Active process owner required'; END IF;
 IF target IS NULL THEN
  IF parent IS NOT NULL THEN
   SELECT * INTO STRICT parent_node FROM public.ims_processes WHERE id=parent;
   IF parent_node.level>=4 OR NOT parent_node.active THEN RAISE EXCEPTION 'Invalid parent'; END IF;
  END IF;
  INSERT INTO public.ims_processes(parent_id,level,code,draft)
  VALUES(parent,coalesce(parent_node.level,0)+1,btrim(identifier),payload) RETURNING * INTO node;
 ELSE
  SELECT * INTO STRICT node FROM public.ims_processes WHERE id=target FOR UPDATE;
  previous:=node.draft;
 END IF;
 IF publish AND (NOT enabled OR coalesce(length(btrim(payload->>'description')),0)=0) THEN RAISE EXCEPTION 'Description and active process required for publication'; END IF;
 IF publish AND node.parent_id IS NOT NULL AND EXISTS(
  WITH RECURSIVE ancestors AS (SELECT * FROM public.ims_processes WHERE id=node.parent_id UNION ALL SELECT p.* FROM public.ims_processes p JOIN ancestors a ON p.id=a.parent_id)
  SELECT 1 FROM ancestors WHERE live IS NULL OR NOT active) THEN RAISE EXCEPTION 'Publish ancestors first'; END IF;
 UPDATE public.ims_processes SET draft=payload,active=enabled,updated_at=clock_timestamp(),
  live=CASE WHEN publish THEN payload ELSE live END,revision=revision+CASE WHEN publish THEN 1 ELSE 0 END WHERE id=node.id RETURNING * INTO node;
 IF publish THEN INSERT INTO public.standard_reference_usage(reference_id) SELECT value::bigint FROM jsonb_array_elements_text(coalesce(payload->'references','[]'::jsonb)) ON CONFLICT DO NOTHING; END IF;
 IF publish THEN INSERT INTO public.ims_process_revisions(process_id,revision,payload,actor_id) VALUES(node.id,node.revision,payload,actor); END IF;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
 VALUES(actor,CASE WHEN publish THEN 'PUBLISH_PROCESS' ELSE 'SAVE_PROCESS' END,'process',node.id::text,coalesce(nullif(btrim(why),''),'Keine zusätzliche Begründung angegeben.'),jsonb_build_object('before',previous,'after',payload,'revision',node.revision,'active',enabled));
 RETURN node.id;
END;
$$;
REVOKE ALL ON FUNCTION save_ims_process(bigint,bigint,bigint,text,jsonb,boolean,boolean,text) FROM PUBLIC;
