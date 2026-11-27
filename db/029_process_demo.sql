ALTER TABLE ims_processes ADD COLUMN demo boolean NOT NULL DEFAULT false;
CREATE TABLE process_demo_settings (
 id boolean PRIMARY KEY DEFAULT true CHECK(id),
 visible boolean NOT NULL DEFAULT false
);
INSERT INTO process_demo_settings DEFAULT VALUES;
CREATE FUNCTION inherit_demo_process() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.parent_id IS NOT NULL THEN SELECT demo INTO NEW.demo FROM ims_processes WHERE id=NEW.parent_id; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER process_demo_inherit BEFORE INSERT ON ims_processes FOR EACH ROW EXECUTE FUNCTION inherit_demo_process();
CREATE FUNCTION mark_demo_process(actor bigint,target bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 UPDATE public.ims_processes SET demo=true WHERE id=target AND parent_id IS NULL AND code LIKE 'DEMO-SIE-%';
 IF NOT FOUND THEN RAISE EXCEPTION 'Demo root required'; END IF;
END;
$$;
CREATE FUNCTION set_process_demo_visibility(actor bigint,enabled boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 UPDATE public.process_demo_settings SET visible=enabled WHERE id;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'SET_PROCESS_DEMO_VISIBILITY','process_demo','sielaff','Demo-Sichtbarkeit geändert.',jsonb_build_object('visible',enabled));
END;
$$;
REVOKE ALL ON FUNCTION mark_demo_process(bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION set_process_demo_visibility(bigint,boolean) FROM PUBLIC;
