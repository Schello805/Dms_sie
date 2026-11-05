-- Existing dedicated LOGIN role; no ownership, write privileges or inherited owner roles.
-- psql -v backup_role=ims_dms_backup -v database_name=ims_dms -f db/backup_grants.sql
GRANT CONNECT ON DATABASE :"database_name" TO :"backup_role";
GRANT USAGE ON SCHEMA public TO :"backup_role";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"backup_role";
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO :"backup_role";
