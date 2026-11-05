CREATE TABLE branding_revisions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_id bigint NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 original_name text NOT NULL,
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
 reason text NOT NULL CHECK(length(trim(reason))>0),
 logo_png bytea NOT NULL, favicon_ico bytea NOT NULL,
 icon_32 bytea NOT NULL, icon_180 bytea NOT NULL, icon_192 bytea NOT NULL
);
CREATE TABLE branding_settings (
 id integer PRIMARY KEY CHECK(id=1),
 revision_id bigint REFERENCES branding_revisions(id)
);
INSERT INTO branding_settings(id) VALUES (1);
CREATE TRIGGER immutable_branding BEFORE UPDATE OR DELETE ON branding_revisions
 FOR EACH ROW EXECUTE FUNCTION reject_mutation();
