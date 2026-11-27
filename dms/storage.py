"""Private storage: no public MEDIA_URL, never serve user files through templates."""
import hashlib
from pathlib import Path
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from . import services as s

from .file_delivery import MAX_BYTES
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
        from .malware import scan
        scan(path)
        file_id = s.query('''INSERT INTO file_objects(storage_key,original_name,media_type,size_bytes,sha256)
            VALUES (%s,%s,%s,%s,%s) RETURNING id''',[key,name,ALLOWED[suffix],size,digest.hexdigest()])[0]['id']
        s.query('INSERT INTO document_upload_origins(document_id) VALUES (%s) ON CONFLICT DO NOTHING',[v['document_id']])
        s.query('INSERT INTO version_files(version_id,file_id,purpose) VALUES (%s,%s,%s)',[version_id,file_id,purpose])
        s.audit(uid,'UPLOAD',version_id,'Datei hinzugefügt',{'file_id':file_id,'sha256':digest.hexdigest()})
    except Exception:
        path.unlink(missing_ok=True)
        raise


def open_download(user, version_id, file_id, public=False):
    from .public_reading import get_read_version
    from .file_delivery import open_verified
    uid,v = get_read_version(user,version_id) if public else s.get_version(user,version_id)
    files = s.query('''SELECT f.* FROM file_objects f JOIN version_files vf ON vf.file_id=f.id
        WHERE vf.version_id=%s AND f.id=%s''',[version_id,file_id])
    if not files:
        raise ValidationError('Datei nicht verfügbar.', code='FILE_UNAVAILABLE')
    file = files[0]
    try:
        source = open_verified(file)
    except ValidationError as error:
        if error.code=='FILE_INTEGRITY':
            s.audit(uid,'INTEGRITY_FAILURE',version_id,'Datei-Prüfsumme oder Dateigröße abweichend',{'file_id':file_id})
        raise
    try:
        s.audit(uid,'DOWNLOAD',version_id,'Dateidownload',{'file_id':file_id})
    except BaseException:
        source.close()
        raise
    return file,source


def download(user, version_id, file_id, public=False):
    """Compatibility API; HTTP endpoints stream via open_download instead."""
    file,source = open_download(user,version_id,file_id,public=public)
    with source:
        return file,source.read()
