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
with connection.cursor() as cursor:
 cursor.execute(sql.SQL('CREATE ROLE ims_ci_app LOGIN PASSWORD {}').format(sql.Literal(os.environ['CI_APP_PASSWORD'])))
 cursor.execute(Path('db/runtime_grants.sql').read_text().replace(':"runtime_role"','ims_ci_app'))
