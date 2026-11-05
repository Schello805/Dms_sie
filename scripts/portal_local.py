#!/usr/bin/env python3
"""Development-only local distribution worker using the existing application role."""
import json
import os
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
values = json.loads((root/'.local/secrets.json').read_text())
env = dict(os.environ,PGHOST='127.0.0.1',PGPORT=os.environ.get('DMS_DEV_PG_PORT','55439'),PGUSER='ims_dms_dev_app',PGPASSWORD=values['app_password'],PGDATABASE='ims_dms_dev',DMS_SECRET_KEY=values['secret_key'],DMS_DEBUG='0',DMS_INTERNAL_HTTP='1')
sys.exit(subprocess.call([sys.executable,str(root/'manage.py'),'process_portal',*sys.argv[1:]],cwd=root,env=env))
