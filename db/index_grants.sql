-- Dedicated existing worker LOGIN role, no owner or application-role membership.
-- psql -v index_role=ims_dms_index -v database_name=ims_dms -f db/index_grants.sql
GRANT CONNECT ON DATABASE :"database_name" TO :"index_role";
GRANT USAGE ON SCHEMA public TO :"index_role";
GRANT SELECT ON file_objects,file_text_indexes TO :"index_role";
GRANT UPDATE ON file_text_indexes TO :"index_role";
