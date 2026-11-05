import json
import os
from pathlib import Path
import subprocess
import uuid
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from dms.backup import binary,verify_backup

class Command(BaseCommand):
    help = 'Backup in einer neuen temporären PostgreSQL-Datenbank wiederherstellen und prüfen; Quelldatenbank bleibt unverändert.'
    def add_arguments(self,parser):
        parser.add_argument('backup')
        parser.add_argument('--pg-bin')
    def handle(self,*args,**options):
        directory = Path(options['backup']).resolve()
        manifest = verify_backup(directory,options['pg_bin'])
        config = settings.DATABASES['default']
        parameters = dict(user=config['USER'],password=config.get('PASSWORD',''),host=config.get('HOST') or None,port=config.get('PORT') or 5432)
        name = 'ims_restore_check_'+uuid.uuid4().hex
        environment = dict(os.environ,PGDATABASE=name,PGUSER=config['USER'],PGPASSWORD=config.get('PASSWORD',''),PGHOST=config.get('HOST',''),PGPORT=str(config.get('PORT') or 5432))
        with psycopg.connect(dbname='postgres',autocommit=True,**parameters) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                try:
                    subprocess.run([binary('pg_restore',options['pg_bin']),'--exit-on-error','--single-transaction','--no-owner','--no-acl','--dbname='+name,str(directory/'database.dump')],env=environment,check=True,capture_output=True,timeout=600)
                except subprocess.CalledProcessError:
                    raise CommandError('Wiederherstellung in der temporären Datenbank fehlgeschlagen.')
                with psycopg.connect(dbname=name,row_factory=dict_row,**parameters) as restored:
                    files = restored.execute('SELECT id,storage_key,size_bytes,sha256 FROM file_objects ORDER BY id').fetchall()
                    if files!=manifest['files']:
                        raise CommandError('Wiederhergestellte Dateireferenzen weichen vom Manifest ab.')
                    for table,count in manifest['row_counts'].items():
                        if table not in ('documents','document_versions','approval_decisions','audit_events','document_withdrawals','audience_groups','audience_memberships','user_workplaces','version_distribution','version_audiences','document_bookmarks','acknowledgement_assignments','acknowledgement_receipts','evidence_records','evidence_retention_events','evidence_disposal_requests','branding_revisions','branding_settings','directory_settings','document_upload_origins','release_validity'):
                            raise CommandError('Unbekannte Tabellenangabe im Manifest.')
                        actual = restored.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n']
                        if actual!=count:
                            raise CommandError('Abweichender Datensatzbestand: '+table)
                    migrations = restored.execute('SELECT app,name FROM django_migrations ORDER BY app,name').fetchall()
                    if migrations!=manifest['migrations']:
                        raise CommandError('Abweichender Migrationsstand.')
                    restored.execute('SELECT current_release(id) FROM documents').fetchall()
                    restored.execute('SELECT count(*) FROM effective_role_assignments').fetchone()
                self.stdout.write(self.style.SUCCESS(f"Restore erfolgreich: Datenbank, Migrationen und {len(files)} Dateireferenzen stimmen mit dem geprüften Backup überein."))
            finally:
                # Only the random database created by this invocation is removed.
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
