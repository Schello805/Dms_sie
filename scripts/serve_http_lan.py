#!/usr/bin/env python3
"""Explicitly requested internal HTTP endpoint; no database network exposure."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--address',required=True)
parser.add_argument('--port',type=int,default=8000)
args = parser.parse_args()
address = ipaddress.IPv4Address(args.address)
if not any(address in ipaddress.ip_network(network) for network in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')) or not 1024 <= args.port <= 65535:
    parser.error('Explizite private IPv4-Adresse und unprivilegierter Port erforderlich.')
root = Path(__file__).resolve().parents[1]
state = root/'.local'
values = json.loads((state/'secrets.json').read_text())
env = dict(os.environ,PGHOST='127.0.0.1',PGPORT=os.environ.get('DMS_DEV_PG_PORT','55439'),PGUSER='ims_dms_dev_app',PGPASSWORD=values['app_password'],PGDATABASE='ims_dms_dev',DMS_SECRET_KEY=values['secret_key'],DMS_DEBUG='0',DMS_INTERNAL_HTTP='1',DMS_ALLOWED_HOSTS=str(address),DMS_MEDIA_ROOT=str(state/'files'),DMS_TRUST_PROXY='0')
print(f'Interner HTTP-Zugang: http://{address}:{args.port}/',flush=True)
sys.exit(subprocess.call([sys.executable,'-m','gunicorn','config.wsgi:application','--bind',f'{address}:{args.port}','--workers','2','--pid',str(state/'lan-http.pid'),'--access-logfile','-'],cwd=root,env=env))
