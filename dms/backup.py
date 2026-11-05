"""Consistent PostgreSQL/file backups; no secrets or live database directories copied."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
import psycopg
from psycopg.rows import dict_row
from django.conf import settings
from django.core.management.base import CommandError


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def binary(name, directory=None):
    candidate = str(Path(directory)/name) if directory else shutil.which(name)
    if not candidate:
        fallback = Path('/opt/homebrew/opt/postgresql@16/bin')/name
        candidate = str(fallback) if fallback.exists() else None
    if not candidate or not Path(candidate).is_file():
        raise CommandError(f'{name} nicht gefunden; --pg-bin setzen.')
    return candidate


def checked_path(root,relative):
    value = PurePosixPath(relative)
    if value.is_absolute() or '..' in value.parts or not value.parts:
        raise CommandError('Ungültiger relativer Sicherungspfad.')
    path = root.joinpath(*value.parts)
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise CommandError('Sicherungspfad verlässt das Sicherungsverzeichnis.')
    return path


def create_backup(destination,pg_bin=None):
    database = settings.DATABASES['default']
    destination = Path(destination).resolve()
    protected_roots = [settings.MEDIA_ROOT.resolve(),*[settings.BASE_DIR/name for name in ('config','dms','db','deploy','docs','scripts')]]
    if any(destination.is_relative_to(path.resolve()) for path in protected_roots):
        raise CommandError('Sicherungsziel darf nicht im Dokumentenspeicher oder in den Quellcodeverzeichnissen liegen.')
    destination.mkdir(mode=0o700,parents=True,exist_ok=True)
    name = datetime.now(timezone.utc).strftime('ims-dms-%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:8]
    stage = destination/(name+'.partial')
    stage.mkdir(mode=0o700)
    (stage/'files').mkdir(mode=0o700)
    environment = dict(os.environ,PGDATABASE=database['NAME'],PGUSER=database['USER'],PGPASSWORD=database.get('PASSWORD',''),PGHOST=database.get('HOST',''),PGPORT=str(database.get('PORT') or '5432'))
    manifest = {'format_version':1,'created_at':datetime.now(timezone.utc).isoformat(),'files':[],'application':[]}
    with psycopg.connect(dbname=database['NAME'],user=database['USER'],password=database.get('PASSWORD',''),host=database.get('HOST') or None,port=database.get('PORT') or 5432,row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = connection.execute('SELECT pg_export_snapshot() AS token').fetchone()['token']
        files = connection.execute('SELECT id,storage_key,size_bytes,sha256 FROM file_objects ORDER BY id').fetchall()
        tables = ['documents','document_versions','approval_decisions','audit_events','document_withdrawals']
        tables += [name for name in ['audience_groups','audience_memberships','user_workplaces','version_distribution','version_audiences','document_bookmarks','acknowledgement_assignments','acknowledgement_receipts','evidence_records','evidence_retention_events','evidence_disposal_requests','branding_revisions','branding_settings','directory_settings','document_upload_origins','release_validity'] if connection.execute('SELECT to_regclass(%s) AS name',[name]).fetchone()['name']]
        manifest['row_counts'] = {table:connection.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] for table in tables}
        manifest['migrations'] = connection.execute('SELECT app,name FROM django_migrations ORDER BY app,name').fetchall()
        try:
            subprocess.run([binary('pg_dump',pg_bin),'--format=custom','--no-owner','--no-acl','--snapshot='+snapshot,'--file='+str(stage/'database.dump')],env=environment,check=True,capture_output=True,timeout=600)
        except subprocess.CalledProcessError:
            raise CommandError('pg_dump fehlgeschlagen; Sicherung bleibt als .partial markiert. Datenbankzugang und Clientversion prüfen.')
        for record in files:
            key = record['storage_key']
            if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
                raise CommandError('Ungültiger Dateischlüssel im Datenbankbestand.')
            source = settings.MEDIA_ROOT/key
            target = stage/'files'/key
            digest = hashlib.sha256()
            size = 0
            descriptor = os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(descriptor,'rb') as reader,target.open('xb') as writer:
                target.chmod(0o600)
                for chunk in iter(lambda:reader.read(1024*1024),b''):
                    writer.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size!=record['size_bytes'] or digest.hexdigest()!=record['sha256']:
                raise CommandError('Dateiintegrität abweichend; keine vollständige Sicherung erzeugt.')
            manifest['files'].append(record)
    (stage/'database.dump').chmod(0o600)
    manifest['database_sha256'] = digest_file(stage/'database.dump')
    # Bundle matching application sources; the selected roots never include .local or .env.
    roots = ['config','dms','db','deploy','docs','scripts']
    candidates = [settings.BASE_DIR/name for name in ('manage.py','requirements.txt','requirements.lock.txt','README.md')]
    for directory in roots:
        candidates.extend(path for path in (settings.BASE_DIR/directory).rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc')
    for source in sorted(candidates):
        if source.is_symlink():
            raise CommandError('Quellcode-Symlinks sind für die Sicherung nicht zulässig.')
        relative = source.relative_to(settings.BASE_DIR).as_posix()
        target = checked_path(stage/'application',relative)
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        shutil.copyfile(source,target)
        target.chmod(0o600)
        manifest['application'].append({'path':relative,'sha256':digest_file(target)})
    manifest_path = stage/'manifest.json'
    manifest_path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    manifest_path.chmod(0o600)
    verify_backup(stage,pg_bin)
    complete = destination/name
    stage.rename(complete)
    return complete


def verify_backup(directory,pg_bin=None):
    directory = Path(directory).resolve()
    manifest = json.loads((directory/'manifest.json').read_text())
    if manifest.get('format_version')!=1:
        raise CommandError('Unbekanntes Sicherungsformat.')
    if digest_file(checked_path(directory,'database.dump'))!=manifest['database_sha256']:
        raise CommandError('Datenbank-Dump stimmt nicht mit dem Manifest überein.')
    for record in manifest['files']:
        key = record['storage_key']
        if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
            raise CommandError('Ungültiger Speicherschlüssel im Manifest.')
        path = checked_path(directory,'files/'+key)
        if path.stat().st_size!=record['size_bytes'] or digest_file(path)!=record['sha256']:
            raise CommandError('Dateiprüfung fehlgeschlagen: '+key)
    for source in manifest['application']:
        if digest_file(checked_path(directory,'application/'+source['path']))!=source['sha256']:
            raise CommandError('Anwendungsdatei stimmt nicht mit dem Manifest überein.')
    try:
        subprocess.run([binary('pg_restore',pg_bin),'--list',str(directory/'database.dump')],check=True,capture_output=True,timeout=60)
    except subprocess.CalledProcessError:
        raise CommandError('PostgreSQL-Sicherungsformat kann nicht gelesen werden.')
    return manifest
