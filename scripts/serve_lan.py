#!/usr/bin/env python3
"""Explicit LAN-only HTTPS endpoint for the local development instance."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--address',required=True,help='Private IPv4-Adresse dieses Rechners')
parser.add_argument('--port',type=int,default=8443)
args = parser.parse_args()
address = ipaddress.IPv4Address(args.address)
private_lan = any(address in ipaddress.ip_network(network) for network in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'])
if not private_lan or not 1024 <= args.port <= 65535:
    parser.error('Eine private LAN-Adresse und ein Port zwischen 1024 und 65535 sind erforderlich.')
state = root/'.local'
secret_file = state/'secrets.json'
if not secret_file.exists():
    sys.exit('Zuerst scripts/dev.py starten.')
pid_file = state/'lan.pid'
if pid_file.exists():
    try:
        os.kill(int(pid_file.read_text().strip()),0)
    except (ProcessLookupError,ValueError):
        pass
    else:
        sys.exit('LAN-Dienst läuft bereits. Vor einem erneuten Start geordnet beenden oder per SIGHUP neu laden.')
values = json.loads(secret_file.read_text())
tls = state/'tls'
tls.mkdir(mode=0o700,exist_ok=True)
openssl = shutil.which('openssl')
if not openssl:
    sys.exit('OpenSSL ist erforderlich.')

def openssl_run(*arguments):
    subprocess.run([openssl,*map(str,arguments)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

if not (tls/'ca.pem').exists():
    openssl_run('req','-x509','-newkey','rsa:3072','-nodes','-keyout',tls/'ca.key','-out',tls/'ca.pem','-days','365','-subj','/CN=DMS Local Development CA','-addext','basicConstraints=critical,CA:TRUE,pathlen:0','-addext','keyUsage=critical,keyCertSign,cRLSign')
    (tls/'ca.key').chmod(0o600)
openssl_run('x509','-in',tls/'ca.pem','-outform','DER','-out',tls/'dms-local-ca.cer')
# A new leaf binds this run to exactly the requested private IP, with a short lifetime.
extensions = tls/'server.ext'
extensions.write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:{address}\n')
openssl_run('req','-new','-newkey','rsa:3072','-nodes','-keyout',tls/'server.key','-out',tls/'server.csr','-subj',f'/CN={address}')
(tls/'server.key').chmod(0o600)
openssl_run('x509','-req','-in',tls/'server.csr','-CA',tls/'ca.pem','-CAkey',tls/'ca.key','-CAcreateserial','-out',tls/'server.pem','-days','30','-extfile',extensions)
env = dict(os.environ,PGHOST='127.0.0.1',PGPORT=os.environ.get('DMS_DEV_PG_PORT','55439'),PGUSER='ims_dms_dev_app',PGPASSWORD=values['app_password'],PGDATABASE='ims_dms_dev',DMS_SECRET_KEY=values['secret_key'],DMS_DEBUG='0',DMS_ALLOWED_HOSTS=str(address),DMS_MEDIA_ROOT=str(state/'files'),DMS_TRUST_PROXY='0')
# Do not permit development overrides to disable HTTPS cookie/redirect protections.
env.pop('DMS_LOCAL_HTTP',None)
print(f'Tablet: https://{address}:{args.port}/',flush=True)
print(f'Öffentliches CA-Zertifikat für die manuelle Einrichtung: {tls / "dms-local-ca.cer"}',flush=True)
sys.exit(subprocess.call([sys.executable,'-m','gunicorn','config.wsgi:application','--bind',f'{address}:{args.port}','--workers','2','--keyfile',str(tls/'server.key'),'--certfile',str(tls/'server.pem'),'--pid',str(state/'lan.pid'),'--access-logfile','-'],cwd=root,env=env))
