-- Permanent URL allocation, independent of revisions and editable display labels.
CREATE TABLE document_links (
 document_id bigint PRIMARY KEY REFERENCES documents(id),
 kind_slug text NOT NULL,number_slug text NOT NULL,
 UNIQUE(kind_slug,number_slug)
);
CREATE FUNCTION document_link_slug(value text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(nullif(btrim(regexp_replace(lower(replace(replace(replace(replace(replace(replace(replace(replace(value,'Ä','Ae'),'Ö','Oe'),'Ü','Ue'),'ä','ae'),'ö','oe'),'ü','ue'),'ß','ss'),'ẞ','ss')),'[^a-z0-9_-]+','-','g'),'-_'),''),'dokument');
$$;
CREATE FUNCTION allocate_document_link(target bigint) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE kind text; base text; candidate text; attempts integer:=0;
BEGIN
 SELECT public.document_link_slug(coalesce(c.display_name,c.name)),public.document_link_slug(d.number)
 INTO STRICT kind,base FROM public.documents d JOIN public.document_categories c ON c.name=d.document_type WHERE d.id=target;
 IF EXISTS(SELECT 1 FROM public.document_links WHERE document_id=target) THEN RETURN; END IF;
 LOOP
  candidate:=CASE WHEN attempts=0 THEN base ELSE base||'--'||target::text||CASE WHEN attempts=1 THEN '' ELSE '-'||attempts::text END END;
  INSERT INTO public.document_links(document_id,kind_slug,number_slug) VALUES(target,kind,candidate) ON CONFLICT DO NOTHING;
  IF FOUND THEN RETURN; END IF;
  IF EXISTS(SELECT 1 FROM public.document_links WHERE document_id=target) THEN RETURN; END IF;
  attempts:=attempts+1;
 END LOOP;
END;
$$;
DO $$ DECLARE doc bigint; BEGIN FOR doc IN SELECT id FROM documents ORDER BY id LOOP PERFORM allocate_document_link(doc); END LOOP; END $$;
CREATE FUNCTION assign_document_link() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN PERFORM public.allocate_document_link(NEW.id); RETURN NEW; END;
$$;
CREATE TRIGGER assign_permanent_document_link AFTER INSERT ON documents FOR EACH ROW EXECUTE FUNCTION assign_document_link();
CREATE TRIGGER protect_permanent_document_link BEFORE UPDATE OR DELETE ON document_links FOR EACH ROW EXECUTE FUNCTION reject_mutation();
REVOKE ALL ON FUNCTION allocate_document_link(bigint),assign_document_link() FROM PUBLIC;
