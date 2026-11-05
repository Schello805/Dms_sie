#!/usr/bin/env python3
"""Administrative Django commands against the private local development database."""
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
secrets_file = root/'.local/secrets.json'
if not secrets_file.exists():
    sys.exit('Zuerst scripts/dev.py starten.')
values = json.loads(secrets_file.read_text())
env = dict(os.environ,PGHOST='127.0.0.1',PGPORT=os.environ.get('DMS_DEV_PG_PORT','55439'),PGUSER=getpass.getuser(),PGPASSWORD=values['owner_password'],PGDATABASE='ims_dms_dev',DMS_SECRET_KEY=values['secret_key'],DMS_DEBUG='1',DMS_MEDIA_ROOT=str(root/'.local/files'),DMS_DEMO_PASSWORD=values['demo_password'])
sys.exit(subprocess.call([sys.executable,str(root/'manage.py'),*sys.argv[1:]],cwd=root,env=env))
