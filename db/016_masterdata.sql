ALTER TABLE departments ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE document_categories ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE document_categories ADD COLUMN display_name text;
UPDATE document_categories SET display_name=name;
CREATE UNIQUE INDEX category_display_name_unique ON document_categories((coalesce(display_name,name)));
ALTER TABLE standards ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE standard_references ADD COLUMN active boolean NOT NULL DEFAULT true;

-- Keep the "ever submitted" fact after a returned draft removes a mapping.
CREATE TABLE standard_reference_usage (
 reference_id bigint PRIMARY KEY REFERENCES standard_references(id),
 first_submitted_at timestamptz DEFAULT clock_timestamp(),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- Older cycles stored hashes, not complete mapping snapshots. Conservatively
-- protect existing definitions if historic workflows exist; never invent history.
INSERT INTO standard_reference_usage(reference_id,first_submitted_at)
 SELECT id,NULL FROM standard_references WHERE EXISTS(SELECT 1 FROM workflow_instances);
CREATE TRIGGER immutable_standard_usage BEFORE UPDATE OR DELETE ON standard_reference_usage FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE FUNCTION record_standard_usage() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 INSERT INTO standard_reference_usage(reference_id) SELECT reference_id FROM version_standard_links WHERE version_id=NEW.version_id ON CONFLICT DO NOTHING;
 RETURN NEW;
END;
$$;
CREATE TRIGGER capture_standard_usage AFTER INSERT ON workflow_instances FOR EACH ROW EXECUTE FUNCTION record_standard_usage();

CREATE FUNCTION guard_used_standard_definition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='standards' THEN
  IF (NEW.name,NEW.edition) IS DISTINCT FROM (OLD.name,OLD.edition) AND EXISTS(
   SELECT 1 FROM standard_references r JOIN standard_reference_usage u ON u.reference_id=r.id WHERE r.standard_id=OLD.id) THEN
   RAISE EXCEPTION 'Used standard definitions are immutable; create a new edition'; END IF;
 ELSE
  IF (NEW.standard_id,NEW.reference,NEW.label) IS DISTINCT FROM (OLD.standard_id,OLD.reference,OLD.label) AND EXISTS(
   SELECT 1 FROM standard_reference_usage WHERE reference_id=OLD.id) THEN
   RAISE EXCEPTION 'Used references are immutable; create a new reference'; END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER preserve_used_standard BEFORE UPDATE ON standards FOR EACH ROW EXECUTE FUNCTION guard_used_standard_definition();
CREATE TRIGGER preserve_used_reference BEFORE UPDATE ON standard_references FOR EACH ROW EXECUTE FUNCTION guard_used_standard_definition();

CREATE FUNCTION require_ims_manager(actor bigint, technical boolean) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active)
 OR (technical AND NOT has_role(actor,'ADMIN',NULL,NULL)) OR (NOT technical AND NOT is_qmb(actor)) THEN
 RAISE EXCEPTION 'Management permission required'; END IF;
END;
$$;
CREATE FUNCTION save_ims_master(actor bigint,kind text,target bigint,data jsonb,why text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE prior jsonb; result jsonb; label text:=trim(data->>'name'); enabled boolean:=coalesce((data->>'active')::boolean,true); parent bigint; place bigint; members bigint[];
BEGIN
 IF kind NOT IN ('categories','departments','locations','standards','references','groups') OR coalesce(length(trim(why)),0)=0 THEN RAISE EXCEPTION 'Invalid master-data request'; END IF;
 PERFORM require_ims_manager(actor,kind='groups');
 PERFORM pg_advisory_xact_lock(hashtext('ims-master-data'));
 IF kind='groups' THEN PERFORM pg_advisory_xact_lock(hashtext('ims-user-roles')); END IF;
 IF kind<>'references' AND (coalesce(length(label),0)=0 OR length(label)>300) THEN RAISE EXCEPTION 'Name required'; END IF;
 CASE kind
 WHEN 'categories' THEN
  SELECT to_jsonb(c) INTO prior FROM document_categories c WHERE id=target FOR UPDATE;
  place:=(data->>'storage_location_id')::bigint;
  IF NOT EXISTS(SELECT 1 FROM storage_locations WHERE id=place AND (active OR (prior->>'storage_location_id')::bigint=place)) THEN RAISE EXCEPTION 'Active storage location required'; END IF;
  IF target IS NULL THEN
   INSERT INTO document_categories(name,display_name,review_interval_months,retention_months,storage_location_id,active)
   VALUES('cat-'||gen_random_uuid()::text,label,(data->>'review_interval_months')::integer,(data->>'retention_months')::integer,place,enabled) RETURNING id INTO target;
  ELSE
   UPDATE document_categories SET display_name=label,review_interval_months=(data->>'review_interval_months')::integer,
    retention_months=(data->>'retention_months')::integer,storage_location_id=place,active=enabled,updated_at=clock_timestamp() WHERE id=target;
  END IF;
  SELECT to_jsonb(c) INTO result FROM document_categories c WHERE id=target;
 WHEN 'departments' THEN
  SELECT to_jsonb(d) INTO prior FROM departments d WHERE id=target FOR UPDATE;
  parent:=(data->>'parent_id')::bigint;
  IF parent IS NOT NULL THEN
   IF NOT EXISTS(SELECT 1 FROM departments WHERE id=parent AND (active OR (prior->>'parent_id')::bigint=parent)) THEN RAISE EXCEPTION 'Active parent department required'; END IF;
   IF EXISTS(WITH RECURSIVE children AS(SELECT id FROM departments WHERE id=target UNION SELECT d.id FROM departments d JOIN children c ON d.parent_id=c.id) SELECT 1 FROM children WHERE id=parent) THEN RAISE EXCEPTION 'Department hierarchy cannot contain cycles'; END IF;
  END IF;
  IF target IS NULL THEN
   INSERT INTO departments(code,name,parent_id,active) VALUES(trim(data->>'code'),label,parent,enabled) RETURNING id INTO target;
  ELSE UPDATE departments SET code=trim(data->>'code'),name=label,parent_id=parent,active=enabled WHERE id=target; END IF;
  SELECT to_jsonb(d) INTO result FROM departments d WHERE id=target;
 WHEN 'locations' THEN
  SELECT to_jsonb(l) INTO prior FROM storage_locations l WHERE id=target FOR UPDATE;
  IF NOT enabled AND EXISTS(SELECT 1 FROM document_categories WHERE storage_location_id=target AND active) THEN RAISE EXCEPTION 'Reassign or deactivate active categories before disabling this location'; END IF;
  IF target IS NULL THEN INSERT INTO storage_locations(name,description,active) VALUES(label,coalesce(data->>'description',''),enabled) RETURNING id INTO target;
  ELSE UPDATE storage_locations SET name=label,description=coalesce(data->>'description',''),active=enabled WHERE id=target; END IF;
  SELECT to_jsonb(l) INTO result FROM storage_locations l WHERE id=target;
 WHEN 'standards' THEN
  SELECT to_jsonb(s) INTO prior FROM standards s WHERE id=target FOR UPDATE;
  IF target IS NULL THEN INSERT INTO standards(name,edition,active) VALUES(label,trim(data->>'edition'),enabled) RETURNING id INTO target;
  ELSE UPDATE standards SET name=label,edition=trim(data->>'edition'),active=enabled WHERE id=target; END IF;
  SELECT to_jsonb(s) INTO result FROM standards s WHERE id=target;
 WHEN 'references' THEN
  SELECT to_jsonb(r) INTO prior FROM standard_references r WHERE id=target FOR UPDATE;
  parent:=(data->>'standard_id')::bigint;
  IF NOT EXISTS(SELECT 1 FROM standards WHERE id=parent AND (active OR (prior->>'standard_id')::bigint=parent)) THEN RAISE EXCEPTION 'Active standard required'; END IF;
  IF target IS NULL THEN INSERT INTO standard_references(standard_id,reference,label,active) VALUES(parent,trim(data->>'reference'),trim(data->>'label'),enabled) RETURNING id INTO target;
  ELSE UPDATE standard_references SET standard_id=parent,reference=trim(data->>'reference'),label=trim(data->>'label'),active=enabled WHERE id=target; END IF;
  SELECT to_jsonb(r) INTO result FROM standard_references r WHERE id=target;
 WHEN 'groups' THEN
  SELECT to_jsonb(g) INTO prior FROM dms_groups g WHERE id=target FOR UPDATE;
  SELECT coalesce(array_agg(DISTINCT value::bigint ORDER BY value::bigint),'{}'::bigint[]) INTO members FROM jsonb_array_elements_text(coalesce(data->'members','[]'::jsonb));
  IF EXISTS(SELECT 1 FROM unnest(members) m(id) WHERE NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=m.id AND ((u.active AND a.is_active) OR EXISTS(SELECT 1 FROM group_memberships WHERE group_id=target AND user_id=m.id)))) THEN RAISE EXCEPTION 'Unknown or inactive new member'; END IF;
  IF EXISTS(SELECT 1 FROM role_assignments WHERE group_id=target AND role NOT IN ('READER','AUTHOR')) AND
    (enabled IS DISTINCT FROM (prior->>'active')::boolean OR members<>ARRAY(SELECT user_id FROM group_memberships WHERE group_id=target ORDER BY user_id)) THEN RAISE EXCEPTION 'Legacy administrative group requires CLI review'; END IF;
  IF target IS NULL THEN INSERT INTO dms_groups(name,active) VALUES(label,enabled) RETURNING id INTO target;
  ELSE UPDATE dms_groups SET name=label,active=enabled WHERE id=target; END IF;
  prior:=coalesce(prior,'{}'::jsonb)||jsonb_build_object('members',ARRAY(SELECT user_id FROM group_memberships WHERE group_id=target ORDER BY user_id));
  DELETE FROM group_memberships WHERE group_id=target AND NOT(user_id=ANY(members));
  INSERT INTO group_memberships(group_id,user_id) SELECT target,m FROM unnest(members) m ON CONFLICT DO NOTHING;
  SELECT to_jsonb(g)||jsonb_build_object('members',members) INTO result FROM dms_groups g WHERE id=target;
  IF NOT has_role(actor,'ADMIN',NULL,NULL) THEN RAISE EXCEPTION 'Own admin access must remain'; END IF;
 END CASE;
 IF result IS NULL THEN RAISE EXCEPTION 'Master-data record not found'; END IF;
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'SAVE_MASTER_DATA','master_data',kind||':'||target::text,why,jsonb_build_object('before',prior,'after',result));
 RETURN target;
END;
$$;
CREATE FUNCTION set_ims_group_grant(actor bigint,target bigint,requested text,department bigint,document bigint,revoke_grant boolean,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM require_ims_manager(actor,true);
 PERFORM pg_advisory_xact_lock(hashtext('ims-user-roles'));
 IF requested NOT IN ('READER','AUTHOR') OR coalesce(length(trim(why)),0)=0 OR (department IS NOT NULL AND document IS NOT NULL) OR NOT EXISTS(SELECT 1 FROM dms_groups WHERE id=target) THEN RAISE EXCEPTION 'Invalid group grant'; END IF;
 IF NOT revoke_grant AND department IS NOT NULL AND NOT EXISTS(SELECT 1 FROM departments WHERE id=department AND active) THEN RAISE EXCEPTION 'Active department required'; END IF;
 IF revoke_grant THEN
 DELETE FROM role_assignments WHERE group_id=target AND role=requested AND department_id IS NOT DISTINCT FROM department AND document_id IS NOT DISTINCT FROM document;
 ELSE INSERT INTO role_assignments(group_id,role,department_id,document_id) VALUES(target,requested,department,document) ON CONFLICT DO NOTHING; END IF;
 IF NOT has_role(actor,'ADMIN',NULL,NULL) THEN RAISE EXCEPTION 'Own admin access must remain'; END IF;
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'GROUP_GRANT','group',target::text,why,jsonb_build_object('role',requested,'department_id',department,'document_id',document,'revoked',revoke_grant));
END;
$$;
CREATE FUNCTION update_ims_profile(actor bigint,target bigint,person text,address text,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE prior jsonb; result jsonb; auth_id bigint;
BEGIN
 PERFORM require_ims_manager(actor,true);
 IF coalesce(length(trim(person)),0)=0 OR coalesce(length(trim(why)),0)=0 THEN RAISE EXCEPTION 'Name and reason required'; END IF;
 SELECT jsonb_build_object('display_name',display_name,'email',email),auth_user_id INTO STRICT prior,auth_id FROM users WHERE id=target FOR UPDATE;
 UPDATE users SET display_name=trim(person),email=coalesce(address,'') WHERE id=target;
 UPDATE auth_user SET email=coalesce(address,'') WHERE id=auth_id;
 result:=jsonb_build_object('display_name',trim(person),'email',coalesce(address,''));
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'UPDATE_PROFILE','user',target::text,why,jsonb_build_object('before',prior,'after',result));
END;
$$;
REVOKE ALL ON FUNCTION record_standard_usage(),require_ims_manager(bigint,boolean),save_ims_master(bigint,text,bigint,jsonb,text),set_ims_group_grant(bigint,bigint,text,bigint,bigint,boolean,text),update_ims_profile(bigint,bigint,text,text,text) FROM PUBLIC;
