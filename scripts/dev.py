#!/usr/bin/env python3
"""Start a loopback-only development instance with persistent, private local data."""
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
STATE = ROOT / '.local'
STATE.mkdir(mode=0o700, exist_ok=True)
SECRET_FILE = STATE / 'secrets.json'
if not SECRET_FILE.exists():
    with SECRET_FILE.open('x') as file:
        SECRET_FILE.chmod(0o600)
        json.dump({name:secrets.token_urlsafe(32) for name in ('secret_key','owner_password','app_password','demo_password')},file)
credentials = json.loads(SECRET_FILE.read_text())
pgbin = os.environ.get('DMS_PG_BIN')
if not pgbin:
    pgctl = shutil.which('pg_ctl')
    if not pgctl:
        pgctl = next((str(p / 'pg_ctl') for p in [Path('/opt/homebrew/opt/postgresql@16/bin'), *sorted(Path('/usr/lib/postgresql').glob('*/bin'),reverse=True)] if (p/'pg_ctl').exists()),None)
    if not pgctl:
        sys.exit('PostgreSQL ab Version 16 installieren oder DMS_PG_BIN setzen.')
    pgbin = str(Path(pgctl).parent)
owner = getpass.getuser()
port = os.environ.get('DMS_DEV_PG_PORT','55439')
socket_dir = STATE/'socket'
socket_dir.mkdir(mode=0o700,exist_ok=True)
data = STATE/'postgres'
env = dict(os.environ,PGHOST='127.0.0.1',PGPORT=port,PGUSER=owner,PGPASSWORD=credentials['owner_password'],PGDATABASE='ims_dms_dev',DMS_SECRET_KEY=credentials['secret_key'],DMS_DEBUG='1',DMS_ALLOWED_HOSTS='localhost,127.0.0.1',DMS_MEDIA_ROOT=str(STATE/'files'),DMS_DEMO_PASSWORD=credentials['demo_password'],DMS_TRUST_PROXY='0')

def run(args, **kwargs):
    return subprocess.run([str(a) for a in args],check=True,env=env,**kwargs)

if not data.exists():
    pwfile = STATE/'init-password'
    with pwfile.open('x') as file:
        pwfile.chmod(0o600)
        file.write(credentials['owner_password'])
    try:
        run([Path(pgbin)/'initdb','-D',data,'--auth=scram-sha-256','--encoding=UTF8','--no-locale',f'--pwfile={pwfile}'])
    finally:
        pwfile.unlink(missing_ok=True)
status = subprocess.run([str(Path(pgbin)/'pg_ctl'),'-D',str(data),'status'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if status.returncode:
    run([Path(pgbin)/'pg_ctl','-D',data,'-l',STATE/'postgres.log','-o',f"-k {socket_dir} -h 127.0.0.1 -p {port}",'start'])
import psycopg
from psycopg import sql
with psycopg.connect(host='127.0.0.1',port=port,user=owner,password=credentials['owner_password'],dbname='postgres',autocommit=True) as connection:
    if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s',['ims_dms_dev']).fetchone():
        connection.execute('CREATE DATABASE ims_dms_dev')
    if not connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',['ims_dms_dev_app']).fetchone():
        connection.execute(sql.SQL('CREATE ROLE ims_dms_dev_app LOGIN PASSWORD {}').format(sql.Literal(credentials['app_password'])))
run([sys.executable,'manage.py','migrate','--noinput'])
run([sys.executable,'manage.py','seed_dev'])
with psycopg.connect(host='127.0.0.1',port=port,user=owner,password=credentials['owner_password'],dbname='ims_dms_dev') as connection:
    connection.execute((ROOT/'db/runtime_grants.sql').read_text().replace(':"runtime_role"','ims_dms_dev_app'))
access = STATE/'access.txt'
with access.open('w') as file:
    access.chmod(0o600)
    file.write('Nur lokale Entwicklungsinstanz: http://127.0.0.1:8000/\n\nKonten: autor, pruefer (QMB), qmb_vertretung, freigabe (Abteilungsleiter / Autor), leser, admin (IT-Systemeinstellungen)\nGemeinsames Entwicklungspasswort: '+credentials['demo_password']+'\n')
print(f'Anwendung: http://127.0.0.1:8000/\nLokale Zugangsdaten: {access}',flush=True)
env.update(PGUSER='ims_dms_dev_app',PGPASSWORD=credentials['app_password'])
run([sys.executable,'manage.py','runserver','127.0.0.1:8000','--noreload'])
