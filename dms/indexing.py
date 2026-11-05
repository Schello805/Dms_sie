"""Leased PostgreSQL queue; extraction runs outside the web and worker process."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from . import services as s


@transaction.atomic
def claim_job():
    s.query("UPDATE file_text_indexes SET status=CASE WHEN attempts>=3 THEN 'FAILED' ELSE 'PENDING' END,lease_token=NULL,error_code='LEASE_EXPIRED' WHERE status='RUNNING' AND claimed_at<clock_timestamp()-interval '2 minutes'")
    token = str(uuid.uuid4())
    rows = s.query('''WITH next AS (SELECT file_id FROM file_text_indexes WHERE status='PENDING' AND attempts<3 ORDER BY file_id FOR UPDATE SKIP LOCKED LIMIT 1)
        UPDATE file_text_indexes i SET status='RUNNING',attempts=attempts+1,lease_token=%s::uuid,claimed_at=clock_timestamp(),error_code=''
        FROM next WHERE i.file_id=next.file_id RETURNING i.file_id,i.lease_token''',[token])
    if not rows:
        return None
    job = rows[0]
    job.update(s.query('SELECT * FROM file_objects WHERE id=%s',[job['file_id']])[0])
    return job


def extract_job(job):
    key = job['storage_key']
    if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
        return {'error':'INTEGRITY_FAILURE'}
    try:
        descriptor = os.open(settings.MEDIA_ROOT/key,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(descriptor,'rb') as source:
            content = source.read(25*1024*1024+1)
    except OSError:
        return {'error':'FILE_UNAVAILABLE'}
    if len(content)!=job['size_bytes'] or hashlib.sha256(content).hexdigest()!=job['sha256']:
        return {'error':'INTEGRITY_FAILURE'}
    kind = Path(job['original_name']).suffix.lower().lstrip('.')
    # No inherited application/database secrets. This is process isolation plus
    # resource limits, not a replacement for a production OS security sandbox.
    environment = {key:value for key,value in os.environ.items() if key in ('PATH','LANG','LC_ALL','SYSTEMROOT')}
    environment.update(PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    try:
        result = subprocess.run([sys.executable,'-I',str(settings.BASE_DIR/'dms/extract_text.py'),kind],input=content,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=environment,timeout=20,check=True)
        output = json.loads(result.stdout)
        if 'error' not in output and (not isinstance(output.get('text'),str) or len(output['text'])>200000):
            return {'error':'LIMIT_EXCEEDED'}
        return output
    except subprocess.TimeoutExpired:
        return {'error':'TIMEOUT'}
    except (subprocess.CalledProcessError,ValueError,OSError):
        return {'error':'EXTRACTION_FAILED'}


@transaction.atomic
def finish_job(job,result):
    error = result.get('error','')
    allowed_errors = {'INTEGRITY_FAILURE','FILE_UNAVAILABLE','TIMEOUT','EXTRACTION_FAILED','INVALID_FILE','LIMIT_EXCEEDED','ENCRYPTED_FILE','UNSUPPORTED_FORMAT'}
    if error and error not in allowed_errors:
        error = 'EXTRACTION_FAILED'
    text = '' if error else result.get('text','')
    status = 'FAILED' if error else ('READY' if text else 'EMPTY')
    return s.query('''UPDATE file_text_indexes SET status=%s,text_content=%s,truncated=%s,error_code=%s,finished_at=clock_timestamp(),lease_token=NULL
        WHERE file_id=%s AND lease_token=%s::uuid AND status='RUNNING' RETURNING file_id''',[status,text,bool(result.get('truncated',False)),error,job['file_id'],str(job['lease_token'])])


def process_one():
    job = claim_job()
    if not job:
        return False
    result = extract_job(job)
    try:
        finish_job(job,result)
    except Exception:
        # A vector/index limit must not terminate the worker or leave text ready.
        finish_job(job,{'error':'EXTRACTION_FAILED'})
    return True


@transaction.atomic
def retry_index(user,version_id,file_id):
    uid,v = s.get_version(user,version_id,lock=True)
    s.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if not s.query('SELECT 1 FROM version_files WHERE version_id=%s AND file_id=%s',[version_id,file_id]):
        raise ValidationError('Datei nicht verfügbar.')
    s.query("UPDATE file_text_indexes SET status='PENDING',text_content='',truncated=false,attempts=0,lease_token=NULL,claimed_at=NULL,finished_at=NULL,error_code='' WHERE file_id=%s",[file_id])
    s.audit(uid,'REINDEX',version_id,'Volltextverarbeitung erneut angefordert',{'file_id':file_id})
