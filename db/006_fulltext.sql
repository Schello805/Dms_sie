CREATE TABLE file_text_indexes (
    file_id bigint PRIMARY KEY REFERENCES file_objects(id),
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RUNNING','READY','EMPTY','FAILED')),
    text_content text NOT NULL DEFAULT '',
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('german'::regconfig,text_content)) STORED,
    truncated boolean NOT NULL DEFAULT false,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
    lease_token uuid,
    claimed_at timestamptz,
    finished_at timestamptz,
    error_code text NOT NULL DEFAULT '',
    CHECK (length(text_content)<=200000)
);
CREATE INDEX file_text_search ON file_text_indexes USING GIN(search_vector);
CREATE INDEX index_queue ON file_text_indexes(status,claimed_at);
CREATE FUNCTION enqueue_file_text() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO file_text_indexes(file_id) VALUES (NEW.id);
    RETURN NEW;
END;
$$;
CREATE TRIGGER enqueue_text AFTER INSERT ON file_objects
    FOR EACH ROW EXECUTE FUNCTION enqueue_file_text();
INSERT INTO file_text_indexes(file_id) SELECT id FROM file_objects;
