-- Preserve operational QMB coverage and recover mail jobs after profile correction.
CREATE OR REPLACE FUNCTION set_operational_roles(actor bigint,target bigint,author_role boolean,qmb_role boolean,admin_role boolean,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE previous jsonb;
BEGIN
 IF NOT public.has_role(actor,'ADMIN',NULL,NULL) THEN RAISE EXCEPTION 'Active IT administrator required'; END IF;
 IF length(trim(why))=0 THEN RAISE EXCEPTION 'Reason required'; END IF;
 IF actor=target AND NOT admin_role THEN RAISE EXCEPTION 'Cannot revoke own administrator access'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ims-user-roles'));
 IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.auth_user a ON a.id=u.auth_user_id WHERE u.id=target AND u.active AND a.is_active) THEN
 RAISE EXCEPTION 'Active account required'; END IF;
 IF EXISTS(SELECT 1 FROM public.role_assignments r JOIN public.group_memberships m ON m.group_id=r.group_id
 JOIN public.dms_groups g ON g.id=r.group_id AND g.active WHERE m.user_id=target AND r.role IN ('AUTHOR','ADMIN')) THEN
 RAISE EXCEPTION 'Inherited group roles must be managed separately'; END IF;
 SELECT jsonb_build_object('admin',settings_admin,'qmb',u.qmb_role,'author',public.has_role(target,'AUTHOR',NULL,NULL),'assignments',COALESCE((SELECT jsonb_agg(jsonb_build_object('role',r.role,'department_id',r.department_id,'document_id',r.document_id)) FROM public.role_assignments r WHERE r.user_id=target),'[]'::jsonb)) INTO previous FROM public.users u WHERE id=target FOR UPDATE;
 IF public.is_qmb(target) AND NOT qmb_role AND NOT EXISTS(SELECT 1 FROM public.users WHERE id<>target AND public.is_qmb(id)) THEN
 RAISE EXCEPTION 'Assign another active QMB first'; END IF;
 DELETE FROM public.role_assignments WHERE user_id=target AND role IN ('AUTHOR','REVIEWER','ADMIN');
 INSERT INTO public.role_assignments(user_id,role) VALUES(target,'READER') ON CONFLICT DO NOTHING;
 IF author_role THEN INSERT INTO public.role_assignments(user_id,role) VALUES(target,'AUTHOR'); END IF;
 UPDATE public.users SET settings_admin=admin_role,qmb_role=CASE WHEN set_operational_roles.qmb_role THEN 'PRIMARY' ELSE 'NONE' END,qmb_approval_lead=false WHERE id=target;
 INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
 VALUES(actor,'CHANGE_USER_ROLES','user',target::text,why,jsonb_build_object('before',previous,'after',jsonb_build_object('author',author_role,'qmb',qmb_role,'admin',admin_role)));
END;
$$;

CREATE OR REPLACE FUNCTION update_ims_profile(actor bigint,target bigint,person text,address text,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE prior jsonb; result jsonb; notification_id bigint; auth_id bigint;
BEGIN
 PERFORM require_ims_manager(actor,true);
 IF coalesce(length(trim(person)),0)=0 OR coalesce(length(trim(why)),0)=0 THEN RAISE EXCEPTION 'Name and reason required'; END IF;
 SELECT jsonb_build_object('display_name',display_name,'email',email),auth_user_id INTO STRICT prior,auth_id FROM users WHERE id=target FOR UPDATE;
 UPDATE users SET display_name=trim(person),email=coalesce(address,'') WHERE id=target;
 UPDATE auth_user SET email=coalesce(address,'') WHERE id=auth_id;
 IF length(trim(coalesce(address,'')))>0 THEN
  FOR notification_id IN UPDATE public.review_notifications SET status='PENDING',error_code='',next_attempt_at=clock_timestamp()
    WHERE recipient_id=target AND status='FAILED' AND error_code='MISSING_EMAIL' RETURNING id
  LOOP
   INSERT INTO public.audit_events(actor_id,action,object_type,object_id,reason,details)
    VALUES(actor,'MAIL_RETRY','notification',notification_id::text,'Empfängeradresse im Benutzerprofil ergänzt','{}'::jsonb);
  END LOOP;
 END IF;
 result:=jsonb_build_object('display_name',trim(person),'email',coalesce(address,''));
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'UPDATE_PROFILE','user',target::text,why,jsonb_build_object('before',prior,'after',result));
END;
$$;
