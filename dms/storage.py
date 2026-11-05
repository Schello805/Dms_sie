"""Private storage: no public MEDIA_URL, never serve user files through templates."""
import hashlib
from pathlib import Path
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from . import services as s

MAX_BYTES = 25 * 1024 * 1024
ALLOWED = {'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.odt':'application/vnd.oasis.opendocument.text','.txt':'text/plain'}

@transaction.atomic
def upload(user, version_id, uploaded, purpose='ORIGINAL'):
    uid,v = s.get_version(user,version_id,lock=True)
    s.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] != 'DRAFT':
        raise ValidationError('Dateien können nur im Entwurf geändert werden.')
    if purpose not in ('ORIGINAL','RELEASE','ATTACHMENT'):
        raise ValidationError('Ungültige Dateiverwendung.')
    if purpose=='RELEASE' and Path(uploaded.name).suffix.lower()!='.pdf':
        raise ValidationError('Eine Lesefassung muss als PDF vorliegen.')
    name = Path(uploaded.name).name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise ValidationError('Erlaubt sind PDF, DOCX, XLSX, ODT und TXT.')
    root = settings.MEDIA_ROOT
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    key = uuid.uuid4().hex
    path = root / key
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open('xb') as output:
            path.chmod(0o600)
            for chunk in uploaded.chunks():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValidationError('Maximale Dateigröße: 25 MiB.')
                output.write(chunk)
                digest.update(chunk)
        if size == 0:
            raise ValidationError('Leere Dateien sind nicht zulässig.')
        file_id = s.query('''INSERT INTO file_objects(storage_key,original_name,media_type,size_bytes,sha256)
            VALUES (%s,%s,%s,%s,%s) RETURNING id''',[key,name,ALLOWED[suffix],size,digest.hexdigest()])[0]['id']
        s.query('INSERT INTO document_upload_origins(document_id) VALUES (%s) ON CONFLICT DO NOTHING',[v['document_id']])
        s.query('INSERT INTO version_files(version_id,file_id,purpose) VALUES (%s,%s,%s)',[version_id,file_id,purpose])
        s.audit(uid,'UPLOAD',version_id,'Datei hinzugefügt',{'file_id':file_id,'sha256':digest.hexdigest()})
    except Exception:
        path.unlink(missing_ok=True)
        raise


def download(user, version_id, file_id):
    uid,v = s.get_version(user,version_id)
    files = s.query('''SELECT f.* FROM file_objects f JOIN version_files vf ON vf.file_id=f.id
        WHERE vf.version_id=%s AND f.id=%s''',[version_id,file_id])
    if not files:
        raise ValidationError('Datei nicht verfügbar.')
    f = files[0]
    # Only generated UUID keys are accepted; database values cannot escape MEDIA_ROOT.
    if len(f['storage_key']) != 32 or any(c not in '0123456789abcdef' for c in f['storage_key']):
        raise ValidationError('Ungültiger Speicherschlüssel.')
    path = settings.MEDIA_ROOT / f['storage_key']
    try:
        with path.open('rb') as source:
            content = source.read(MAX_BYTES + 1)
    except OSError:
        raise ValidationError('Datei im Speicher nicht verfügbar.')
    if len(content) != f['size_bytes'] or hashlib.sha256(content).hexdigest() != f['sha256']:
        s.audit(uid,'INTEGRITY_FAILURE',version_id,'Datei-Prüfsumme oder Dateigröße abweichend',{'file_id':file_id})
        raise ValidationError('Integritätsprüfung fehlgeschlagen. Administration verständigen.')
    s.audit(uid,'DOWNLOAD',version_id,'Dateidownload',{'file_id':file_id})
    return f,content
