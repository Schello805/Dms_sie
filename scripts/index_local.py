#!/usr/bin/env python3
"""Run the development index worker with its own restricted PostgreSQL role."""
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
if 'index_password' not in values:
    values['index_password'] = secrets.token_urlsafe(32)
    with tempfile.NamedTemporaryFile(mode='w',dir=state,prefix='secret-update-',delete=False) as file:
        temporary = Path(file.name)
        json.dump(values,file)
    temporary.chmod(0o600)
    temporary.replace(state/'secrets.json')
parameters = dict(host='127.0.0.1',port=os.environ.get('DMS_DEV_PG_PORT','55439'),user=getpass.getuser(),password=values['owner_password'])
with psycopg.connect(dbname='ims_dms_dev',**parameters) as connection:
    if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='ims_dms_dev_index'").fetchone():
        connection.execute(sql.SQL('CREATE ROLE ims_dms_dev_index LOGIN PASSWORD {}').format(sql.Literal(values['index_password'])))
    connection.execute((root/'db/index_grants.sql').read_text().replace(':"index_role"','ims_dms_dev_index').replace(':"database_name"','ims_dms_dev'))
environment = dict(os.environ,PGHOST='127.0.0.1',PGPORT=parameters['port'],PGUSER='ims_dms_dev_index',PGPASSWORD=values['index_password'],PGDATABASE='ims_dms_dev',DMS_SECRET_KEY=values['secret_key'],DMS_DEBUG='0',DMS_MEDIA_ROOT=str(state/'files'))
print('Lokaler Volltext-Worker mit eingeschränkter Datenbankrolle gestartet.',flush=True)
sys.exit(subprocess.call([sys.executable,str(root/'manage.py'),'process_index',*sys.argv[1:]],cwd=root,env=environment))
