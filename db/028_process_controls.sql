CREATE TABLE process_controls (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 process_id bigint NOT NULL REFERENCES ims_processes(id),
 kind text NOT NULL CHECK(kind IN ('risk','kpi')),
 payload jsonb NOT NULL,
 active boolean NOT NULL DEFAULT true,
 revision integer NOT NULL DEFAULT 1,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX process_controls_process ON process_controls(process_id,kind);
CREATE TABLE process_control_history (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 control_id bigint NOT NULL REFERENCES process_controls(id),
 revision integer NOT NULL,
 payload jsonb NOT NULL,
 active boolean NOT NULL,
 actor_id bigint NOT NULL REFERENCES users(id),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(control_id,revision)
);
CREATE TABLE process_measurements (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 control_id bigint NOT NULL REFERENCES process_controls(id),
 measured_on date NOT NULL,
 value numeric(20,6) NOT NULL,
 definition jsonb NOT NULL,
 note text NOT NULL DEFAULT '',
 actor_id bigint NOT NULL REFERENCES users(id),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX process_measurement_latest ON process_measurements(control_id,measured_on DESC,id DESC);
CREATE TRIGGER process_control_history_guard BEFORE UPDATE OR DELETE ON process_control_history FOR EACH ROW EXECUTE FUNCTION guard_process_revision();
CREATE TRIGGER process_measurement_guard BEFORE UPDATE OR DELETE ON process_measurements FOR EACH ROW EXECUTE FUNCTION guard_process_revision();
CREATE FUNCTION save_process_control(actor bigint,process bigint,target bigint,control_kind text,data jsonb,enabled boolean,expected integer,why text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE item public.process_controls; old_data jsonb;
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 PERFORM 1 FROM public.ims_processes WHERE id=process AND active FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Active process required'; END IF;
 IF control_kind NOT IN ('risk','kpi') OR jsonb_typeof(data)<>'object' OR coalesce(length(btrim(data->>'title')),0) NOT BETWEEN 1 AND 300 THEN RAISE EXCEPTION 'Invalid control'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.auth_user a ON a.id=u.auth_user_id WHERE u.id=(data->>'owner_id')::bigint AND u.active AND a.is_active) THEN RAISE EXCEPTION 'Active owner required'; END IF;
 IF control_kind='risk' THEN
  IF coalesce((data->>'probability')::int,0) NOT BETWEEN 1 AND 5 OR coalesce((data->>'impact')::int,0) NOT BETWEEN 1 AND 5 OR coalesce(data->>'status','') NOT IN ('open','progress','closed','accepted') THEN RAISE EXCEPTION 'Invalid risk assessment'; END IF;
  IF ((data->>'residual_probability') IS NOT NULL AND (data->>'residual_probability')::int NOT BETWEEN 1 AND 5) OR ((data->>'residual_impact') IS NOT NULL AND (data->>'residual_impact')::int NOT BETWEEN 1 AND 5) OR ((data->>'residual_probability') IS NULL) <> ((data->>'residual_impact') IS NULL) THEN RAISE EXCEPTION 'Incomplete residual assessment'; END IF;
  IF data->>'status' IN ('closed','accepted') AND coalesce(length(btrim(data->>'effectiveness')),0)=0 THEN RAISE EXCEPTION 'Effectiveness required'; END IF;
  IF data->>'status'='progress' AND (coalesce(length(btrim(data->>'action')),0)=0 OR data->>'due_on' IS NULL) THEN RAISE EXCEPTION 'Action and due date required'; END IF;
  PERFORM (data->>'due_on')::date;
 ELSE
  IF coalesce(length(btrim(data->>'unit')),0) NOT BETWEEN 1 AND 40 OR coalesce(data->>'direction','') NOT IN ('gte','lte') OR data->>'target' IS NULL OR coalesce((data->>'interval_months')::int,0) NOT BETWEEN 1 AND 120 THEN RAISE EXCEPTION 'Invalid KPI definition'; END IF;
  IF (data->>'target')::numeric::text IN ('NaN','Infinity','-Infinity') THEN RAISE EXCEPTION 'Finite target required'; END IF;
  PERFORM (data->>'target')::numeric(20,6);
  PERFORM (data->>'first_due')::date;
  IF data->>'first_due' IS NULL THEN RAISE EXCEPTION 'First measurement date required'; END IF;
 END IF;
 IF target IS NULL THEN
  INSERT INTO public.process_controls(process_id,kind,payload,active) VALUES(process,control_kind,data,enabled) RETURNING * INTO item;
 ELSE
  SELECT * INTO STRICT item FROM public.process_controls WHERE id=target AND process_id=process AND kind=control_kind FOR UPDATE;
  IF item.revision<>expected THEN RAISE EXCEPTION 'Concurrent update'; END IF;
  old_data:=item.payload;
  UPDATE public.process_controls SET payload=data,active=enabled,revision=revision+1,updated_at=clock_timestamp() WHERE id=target RETURNING * INTO item;
 END IF;
 INSERT INTO public.process_control_history(control_id,revision,payload,active,actor_id) VALUES(item.id,item.revision,data,enabled,actor);
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'SAVE_PROCESS_CONTROL','process_control',item.id::text,coalesce(nullif(btrim(why),''),'Keine zusätzliche Begründung angegeben.'),jsonb_build_object('process_id',process,'kind',control_kind,'before',old_data,'after',data,'revision',item.revision,'active',enabled));
 RETURN item.id;
END;
$$;
CREATE FUNCTION record_process_measurement(actor bigint,target bigint,day date,amount numeric,comment text,expected integer) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE item public.process_controls; result bigint;
BEGIN
 IF NOT public.is_qmb(actor) THEN RAISE EXCEPTION 'QMB required'; END IF;
 SELECT * INTO STRICT item FROM public.process_controls WHERE id=target AND kind='kpi' AND active FOR UPDATE;
 IF item.revision<>expected THEN RAISE EXCEPTION 'Definition changed'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.ims_processes WHERE id=item.process_id AND active) OR day IS NULL OR day>current_date OR amount IS NULL OR amount::text IN ('NaN','Infinity','-Infinity') OR length(coalesce(comment,''))>4000 THEN RAISE EXCEPTION 'Invalid measurement'; END IF;
 INSERT INTO public.process_measurements(control_id,measured_on,value,definition,note,actor_id) VALUES(target,day,amount,item.payload,coalesce(comment,''),actor) RETURNING id INTO result;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'RECORD_PROCESS_MEASUREMENT','process_measurement',result::text,'Messwert erfasst.',jsonb_build_object('control_id',target,'measured_on',day,'value',amount,'note',comment));
 RETURN result;
END;
$$;
REVOKE ALL ON FUNCTION save_process_control(bigint,bigint,bigint,text,jsonb,boolean,integer,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION record_process_measurement(bigint,bigint,date,numeric,text,integer) FROM PUBLIC;
