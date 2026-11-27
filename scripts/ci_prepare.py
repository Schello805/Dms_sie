"""Synthetic CI data only; never called by the production installer."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if os.environ.get('CI')!='true':raise SystemExit('Only for isolated CI runners.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.db import connection
from psycopg import sql
from pathlib import Path
from dms import services as s
from dms.simple_workflow import upload_document,decide
call_command('migrate',interactive=False)
call_command('seed_dev')
author=get_user_model().objects.get(username='autor');qmb=get_user_model().objects.get(username='pruefer')
dep=s.query("SELECT id FROM departments WHERE code='IT'")[0]['id']
for index in range(32):
 vid=upload_document(author,{'number':f'CI-LAZY-{index:03d}','title':f'CI Lazy {index:03d}','document_type':'Arbeitsanweisung','department':dep,'classification':'INTERNAL','change_summary':'CI fixture','effective_from':timezone.now()},SimpleUploadedFile('ci.txt',b'Synthetic CI document'),True)
 decide(qmb,vid,True,'CI review')
# Large synthetic original for the real, memory-constrained Gunicorn download test.
import json
vid=upload_document(author,{'number':'CI-DOWNLOAD-LARGE','title':'CI download fixture','document_type':'Arbeitsanweisung','department':dep,'classification':'INTERNAL','change_summary':'CI fixture','effective_from':timezone.now()},SimpleUploadedFile('Qualitätsnachweis.txt',b'x'*(24*1024*1024)),True)
decide(qmb,vid,True,'CI review')
file=s.query('SELECT f.* FROM file_objects f JOIN version_files vf ON vf.file_id=f.id WHERE vf.version_id=%s',[vid])[0]
small=s.query("SELECT v.id,vf.file_id FROM documents d JOIN document_versions v ON v.document_id=d.id JOIN version_files vf ON vf.version_id=v.id WHERE d.number='CI-LAZY-000'")[0]
Path('test-results').mkdir(exist_ok=True)
Path('test-results/download-fixture.json').write_text(json.dumps({'large':{'path':f'/versions/{vid}/files/{file["id"]}/','size':file['size_bytes'],'sha256':file['sha256']},'preview':f'/versions/{small["id"]}/files/{small["file_id"]}/preview/?download=1'}))

with connection.cursor() as cursor:
 cursor.execute(sql.SQL('CREATE ROLE ims_ci_app LOGIN PASSWORD {}').format(sql.Literal(os.environ['CI_APP_PASSWORD'])))
 cursor.execute(Path('db/runtime_grants.sql').read_text().replace(':"runtime_role"','ims_ci_app'))
