CREATE TABLE directory_settings (
 id integer PRIMARY KEY CHECK(id=1),
 directory_type text NOT NULL DEFAULT 'AD' CHECK(directory_type IN ('AD','LDAP')),
 host text NOT NULL DEFAULT '', port integer NOT NULL DEFAULT 636 CHECK(port BETWEEN 1 AND 65535),
 security text NOT NULL DEFAULT 'LDAPS' CHECK(security IN ('LDAPS','STARTTLS')),
 domain text NOT NULL DEFAULT '', base_dn text NOT NULL DEFAULT '',
 bind_identity text NOT NULL DEFAULT '', password_ciphertext text NOT NULL DEFAULT '',
 user_base_dn text NOT NULL DEFAULT '',
 user_filter text NOT NULL DEFAULT '(&(objectCategory=person)(objectClass=user)(sAMAccountName={username}))',
 username_attribute text NOT NULL DEFAULT 'sAMAccountName',
 name_attribute text NOT NULL DEFAULT 'displayName', email_attribute text NOT NULL DEFAULT 'mail',
 identity_attribute text NOT NULL DEFAULT 'objectGUID',
 group_base_dn text NOT NULL DEFAULT '', group_filter text NOT NULL DEFAULT '(objectClass=group)',
 membership_attribute text NOT NULL DEFAULT 'memberOf',
 timeout_seconds integer NOT NULL DEFAULT 5 CHECK(timeout_seconds BETWEEN 1 AND 60),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO directory_settings(id) VALUES (1);
