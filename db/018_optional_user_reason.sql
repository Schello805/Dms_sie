-- Optional user-entered explanation; audit identity, time and action remain mandatory.
CREATE OR REPLACE FUNCTION create_local_account(actor bigint, login text, encoded text, person text, address text, why text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE auth_id bigint; target bigint;
BEGIN
 why := coalesce(nullif(trim(why),''),'Keine zusätzliche Begründung angegeben.');
 IF NOT has_role(actor,'ADMIN',NULL,NULL) OR NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active) THEN RAISE EXCEPTION 'Active IT administrator required'; END IF;
 IF login !~ '^[a-zA-Z0-9_.@+-]{1,150}$' OR length(trim(person))=0 OR encoded !~ '^(pbkdf2_sha256|argon2|scrypt|bcrypt_sha256)\$' THEN RAISE EXCEPTION 'Invalid account data'; END IF;
 INSERT INTO auth_user(username,password,is_superuser,is_staff,is_active,first_name,last_name,email,date_joined)
 VALUES(login,encoded,false,false,true,'','',coalesce(address,''),clock_timestamp()) RETURNING id INTO auth_id;
 INSERT INTO users(auth_user_id,display_name,email) VALUES(auth_id,person,coalesce(address,'')) RETURNING id INTO target;
 INSERT INTO role_assignments(user_id,role) VALUES(target,'READER');
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'CREATE_ACCOUNT','user',target::text,why,jsonb_build_object('username',login,'display_name',person));
 RETURN target;
END;
$$;

CREATE OR REPLACE FUNCTION set_account_active(actor bigint,target bigint,enabled boolean,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE auth_id bigint;
BEGIN
 why := coalesce(nullif(trim(why),''),'Keine zusätzliche Begründung angegeben.');
 IF NOT has_role(actor,'ADMIN',NULL,NULL) OR NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active) THEN RAISE EXCEPTION 'Active IT administrator required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ims-user-roles'));
 IF actor=target THEN RAISE EXCEPTION 'Cannot deactivate own account'; END IF;
 SELECT auth_user_id INTO STRICT auth_id FROM users WHERE id=target FOR UPDATE;
 IF NOT enabled AND is_qmb(target) AND NOT EXISTS(SELECT 1 FROM users WHERE id<>target AND is_qmb(id)) THEN RAISE EXCEPTION 'Assign another active QMB first'; END IF;
 UPDATE users SET active=enabled WHERE id=target;
 UPDATE auth_user SET is_active=enabled WHERE id=auth_id;
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'SET_ACCOUNT_ACTIVE','user',target::text,why,jsonb_build_object('active',enabled));
END;
$$;

CREATE OR REPLACE FUNCTION set_local_password(actor bigint,target bigint,encoded text,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE auth_id bigint;
BEGIN
 why := coalesce(nullif(trim(why),''),'Keine zusätzliche Begründung angegeben.');
 IF NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active) OR (actor<>target AND NOT has_role(actor,'ADMIN',NULL,NULL)) THEN RAISE EXCEPTION 'Not authorized'; END IF;
 IF EXISTS(SELECT 1 FROM external_identities WHERE user_id=target) THEN RAISE EXCEPTION 'Directory password must be managed externally'; END IF;
 IF encoded !~ '^(pbkdf2_sha256|argon2|scrypt|bcrypt_sha256)\$' THEN RAISE EXCEPTION 'Invalid password change'; END IF;
 SELECT auth_user_id INTO STRICT auth_id FROM users WHERE id=target FOR UPDATE;
 UPDATE auth_user SET password=encoded WHERE id=auth_id;
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason) VALUES(actor,'CHANGE_LOCAL_PASSWORD','user',target::text,why);
END;
$$;

CREATE OR REPLACE FUNCTION set_operational_roles(actor bigint,target bigint,author_role boolean,qmb_role boolean,admin_role boolean,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE previous jsonb;
BEGIN
 why := coalesce(nullif(trim(why),''),'Keine zusätzliche Begründung angegeben.');
 IF NOT public.has_role(actor,'ADMIN',NULL,NULL) THEN RAISE EXCEPTION 'Active IT administrator required'; END IF;
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
 why := coalesce(nullif(trim(why),''),'Keine zusätzliche Begründung angegeben.');
 PERFORM require_ims_manager(actor,true);
 IF coalesce(length(trim(person)),0)=0 THEN RAISE EXCEPTION 'Name required'; END IF;
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
