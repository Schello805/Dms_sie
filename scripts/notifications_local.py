#!/usr/bin/env python3
"""Run local reminders with a dedicated PostgreSQL role; default configuration is disabled."""
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import psycopg
from psycopg import sql

root = Path(__file__).resolve().parents[1]
state = root/'.local'
values = json.loads((state/'secrets.json').read_text())
if 'notification_password' not in values:
    values['notification_password'] = secrets.token_urlsafe(32)
    with tempfile.NamedTemporaryFile(mode='w',dir=state,prefix='secret-update-',delete=False) as file:
        temporary = Path(file.name)
        json.dump(values,file)
    temporary.chmod(0o600)
    temporary.replace(state/'secrets.json')
parameters = dict(host='127.0.0.1',port=os.environ.get('DMS_DEV_PG_PORT','55439'),user=getpass.getuser(),password=values['owner_password'])
with psycopg.connect(dbname='ims_dms_dev',**parameters) as connection:
    if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='ims_dms_dev_notify'").fetchone():
        connection.execute(sql.SQL('CREATE ROLE ims_dms_dev_notify LOGIN PASSWORD {}').format(sql.Literal(values['notification_password'])))
    connection.execute((root/'db/notification_grants.sql').read_text().replace(':"notification_role"','ims_dms_dev_notify').replace(':"database_name"','ims_dms_dev'))
environment = dict(os.environ,PGHOST='127.0.0.1',PGPORT=parameters['port'],PGUSER='ims_dms_dev_notify',PGPASSWORD=values['notification_password'],PGDATABASE='ims_dms_dev',DMS_SECRET_KEY=values['secret_key'],DMS_DEBUG='0',DMS_MEDIA_ROOT=str(state/'files'),DMS_HEALTH_DIR=str(state/'health'))
print('Lokaler Erinnerungsdienst gestartet; Versand nur bei aktivierter SMTP-Konfiguration.',flush=True)
sys.exit(subprocess.call([sys.executable,str(root/'manage.py'),'process_notifications',*sys.argv[1:]],cwd=root,env=environment))
