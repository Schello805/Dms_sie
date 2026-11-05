-- Account lifecycle through narrow functions, never direct auth-table privileges.
CREATE FUNCTION create_local_account(actor bigint, login text, encoded text, person text, address text, why text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE auth_id bigint; target bigint;
BEGIN
 IF NOT has_role(actor,'ADMIN',NULL,NULL) OR NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active) THEN RAISE EXCEPTION 'Active IT administrator required'; END IF;
 IF login !~ '^[a-zA-Z0-9_.@+-]{1,150}$' OR length(trim(person))=0 OR length(trim(why))=0 OR encoded !~ '^(pbkdf2_sha256|argon2|scrypt|bcrypt_sha256)\$' THEN RAISE EXCEPTION 'Invalid account data'; END IF;
 INSERT INTO auth_user(username,password,is_superuser,is_staff,is_active,first_name,last_name,email,date_joined)
 VALUES(login,encoded,false,false,true,'','',coalesce(address,''),clock_timestamp()) RETURNING id INTO auth_id;
 INSERT INTO users(auth_user_id,display_name,email) VALUES(auth_id,person,coalesce(address,'')) RETURNING id INTO target;
 INSERT INTO role_assignments(user_id,role) VALUES(target,'READER');
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'CREATE_ACCOUNT','user',target::text,why,jsonb_build_object('username',login,'display_name',person));
 RETURN target;
END;
$$;
CREATE FUNCTION set_account_active(actor bigint,target bigint,enabled boolean,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE auth_id bigint;
BEGIN
 IF NOT has_role(actor,'ADMIN',NULL,NULL) OR NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active) THEN RAISE EXCEPTION 'Active IT administrator required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('ims-user-roles'));
 IF actor=target OR length(trim(why))=0 THEN RAISE EXCEPTION 'Cannot deactivate own account or omit reason'; END IF;
 SELECT auth_user_id INTO STRICT auth_id FROM users WHERE id=target FOR UPDATE;
 IF NOT enabled AND is_qmb(target) AND NOT EXISTS(SELECT 1 FROM users WHERE id<>target AND is_qmb(id)) THEN RAISE EXCEPTION 'Assign another active QMB first'; END IF;
 UPDATE users SET active=enabled WHERE id=target;
 UPDATE auth_user SET is_active=enabled WHERE id=auth_id;
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES(actor,'SET_ACCOUNT_ACTIVE','user',target::text,why,jsonb_build_object('active',enabled));
END;
$$;
CREATE FUNCTION set_local_password(actor bigint,target bigint,encoded text,why text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE auth_id bigint;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=actor AND u.active AND a.is_active) OR (actor<>target AND NOT has_role(actor,'ADMIN',NULL,NULL)) THEN RAISE EXCEPTION 'Not authorized'; END IF;
 IF EXISTS(SELECT 1 FROM external_identities WHERE user_id=target) THEN RAISE EXCEPTION 'Directory password must be managed externally'; END IF;
 IF length(trim(why))=0 OR encoded !~ '^(pbkdf2_sha256|argon2|scrypt|bcrypt_sha256)\$' THEN RAISE EXCEPTION 'Invalid password change'; END IF;
 SELECT auth_user_id INTO STRICT auth_id FROM users WHERE id=target FOR UPDATE;
 UPDATE auth_user SET password=encoded WHERE id=auth_id;
 INSERT INTO audit_events(actor_id,action,object_type,object_id,reason) VALUES(actor,'CHANGE_LOCAL_PASSWORD','user',target::text,why);
END;
$$;
REVOKE ALL ON FUNCTION create_local_account(bigint,text,text,text,text,text),set_account_active(bigint,bigint,boolean,text),set_local_password(bigint,bigint,text,text) FROM PUBLIC;
