CREATE TABLE process_bpmn (
 process_id bigint PRIMARY KEY REFERENCES ims_processes(id),
 draft_xml text NOT NULL CHECK(octet_length(draft_xml)<=2097152),
 live_xml text,
 edit_version integer NOT NULL DEFAULT 0,
 revision integer NOT NULL DEFAULT 0,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE process_bpmn_revisions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 process_id bigint NOT NULL REFERENCES ims_processes(id),
 revision integer NOT NULL,
 xml text NOT NULL,
 actor_id bigint NOT NULL REFERENCES users(id),
 published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(process_id,revision)
);
CREATE TRIGGER process_bpmn_revision_guard BEFORE UPDATE OR DELETE ON process_bpmn_revisions FOR EACH ROW EXECUTE FUNCTION guard_process_revision();
CREATE FUNCTION save_process_bpmn(actor bigint,target bigint,content text,expected integer,publish boolean,why text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE item public.process_bpmn;
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 PERFORM 1 FROM public.ims_processes WHERE id=target AND active FOR SHARE;
 IF NOT FOUND OR content IS NULL OR octet_length(content)>2097152 THEN RAISE EXCEPTION 'Active process and BPMN content required'; END IF;
 IF publish AND EXISTS(WITH RECURSIVE ancestors AS (SELECT * FROM public.ims_processes WHERE id=target UNION ALL SELECT p.* FROM public.ims_processes p JOIN ancestors a ON p.id=a.parent_id) SELECT 1 FROM ancestors WHERE NOT active OR live IS NULL) THEN RAISE EXCEPTION 'Publish processes first'; END IF;
 INSERT INTO public.process_bpmn(process_id,draft_xml) VALUES(target,content) ON CONFLICT DO NOTHING;
 SELECT * INTO STRICT item FROM public.process_bpmn WHERE process_id=target FOR UPDATE;
 IF item.edit_version IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Concurrent diagram update'; END IF;
 UPDATE public.process_bpmn SET draft_xml=content,live_xml=CASE WHEN publish THEN content ELSE live_xml END,edit_version=edit_version+1,revision=revision+CASE WHEN publish THEN 1 ELSE 0 END,updated_at=clock_timestamp() WHERE process_id=target RETURNING * INTO item;
 IF publish THEN INSERT INTO public.process_bpmn_revisions(process_id,revision,xml,actor_id) VALUES(target,item.revision,content,actor); END IF;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,CASE WHEN publish THEN 'PUBLISH_BPMN' ELSE 'SAVE_BPMN' END,'process_bpmn',target::text,coalesce(nullif(btrim(why),''),'Keine zusätzliche Begründung angegeben.'),jsonb_build_object('edit_version',item.edit_version,'revision',item.revision,'bytes',octet_length(content)));
 RETURN item.edit_version;
END;
$$;
REVOKE ALL ON FUNCTION save_process_bpmn(bigint,bigint,text,integer,boolean,text) FROM PUBLIC;
