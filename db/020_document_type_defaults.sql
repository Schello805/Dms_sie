-- Display labels change without rewriting immutable document type keys or versions.
WITH defaults(old_name,label) AS (VALUES
 ('Arbeitsanweisung','Arbeitsanweisungen'),('Prozess','Prozessbeschreibungen'),
 ('Richtlinie','Richtlinien'),('Vorlage','Vorlagen'),('Externe Norm','Normen'))
UPDATE document_categories c SET display_name=d.label FROM defaults d
WHERE c.name=d.old_name AND coalesce(c.display_name,c.name)=d.old_name
AND NOT EXISTS(SELECT 1 FROM document_categories other WHERE other.id<>c.id AND coalesce(other.display_name,other.name)=d.label);
WITH defaults(label) AS (VALUES ('Arbeitsanweisungen'),('Handbücher'),('Normen'),('Prozessbeschreibungen'),('Richtlinien'),('Vorlagen'))
INSERT INTO document_categories(name,display_name,storage_location_id)
SELECT 'cat-'||gen_random_uuid()::text,d.label,(SELECT id FROM storage_locations WHERE active ORDER BY id LIMIT 1)
FROM defaults d WHERE NOT EXISTS(SELECT 1 FROM document_categories c WHERE lower(coalesce(c.display_name,c.name))=lower(d.label))
AND EXISTS(SELECT 1 FROM storage_locations WHERE active);
-- Retain custom names and existing allocations. Older extra types remain manageable,
-- but are no longer offered by default for new uploads.
UPDATE document_categories SET active=false WHERE name IN ('Betriebsanweisung','SOP') AND coalesce(display_name,name)=name
AND NOT EXISTS(SELECT 1 FROM documents d WHERE d.document_type=document_categories.name);
