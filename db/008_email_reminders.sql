CREATE TABLE notification_settings (
    id smallint PRIMARY KEY DEFAULT 1 CHECK (id=1),
    enabled boolean NOT NULL DEFAULT false,
    reminder_days integer NOT NULL DEFAULT 30 CHECK (reminder_days BETWEEN 0 AND 3650),
    smtp_host text NOT NULL DEFAULT '',
    smtp_port integer NOT NULL DEFAULT 587 CHECK (smtp_port BETWEEN 1 AND 65535),
    smtp_security text NOT NULL DEFAULT 'STARTTLS' CHECK (smtp_security IN ('STARTTLS','SSL','NONE')),
    smtp_username text NOT NULL DEFAULT '',
    password_ciphertext text NOT NULL DEFAULT '',
    sender_email text NOT NULL DEFAULT '',
    base_url text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO notification_settings(id) VALUES (1);
CREATE TABLE review_notifications (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id bigint NOT NULL REFERENCES document_versions(id),
    recipient_id bigint NOT NULL REFERENCES users(id),
    due_on date NOT NULL,
    kind text NOT NULL CHECK (kind IN ('BEFORE','DUE')),
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SENDING','SENT','FAILED','CANCELLED','UNCERTAIN')),
    recipient_email text NOT NULL DEFAULT '',
    message_id text NOT NULL UNIQUE,
    attempts integer NOT NULL DEFAULT 0,
    lease_token uuid,
    claimed_at timestamptz,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    sent_at timestamptz,
    error_code text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(version_id,recipient_id,due_on,kind)
);
CREATE INDEX mail_queue ON review_notifications(status,next_attempt_at,id);
