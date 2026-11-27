"""Bounded verification and file-backed HTTP responses for private stored files."""
import hashlib
import logging
import os
from pathlib import PurePosixPath
import stat
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponse

MAX_BYTES = 25 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


def open_verified(file):
    key = file['storage_key']
    if not isinstance(key, str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
        raise ValidationError('Ungültiger Speicherschlüssel.', code='FILE_KEY')
    source = None
    try:
        descriptor = os.open(settings.MEDIA_ROOT/key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            source = os.fdopen(descriptor, 'rb')
        except BaseException:
            os.close(descriptor)
            raise
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValidationError('Datei im Speicher nicht verfügbar.', code='FILE_UNAVAILABLE')
        if info.st_size!=file['size_bytes'] or not 0<info.st_size<=MAX_BYTES:
            raise ValidationError('Integritätsprüfung fehlgeschlagen. Administration verständigen.', code='FILE_INTEGRITY')
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(CHUNK_BYTES):
            size += len(chunk)
            if size>MAX_BYTES:
                raise ValidationError('Integritätsprüfung fehlgeschlagen. Administration verständigen.', code='FILE_INTEGRITY')
            digest.update(chunk)
        if size!=file['size_bytes'] or digest.hexdigest()!=file['sha256']:
            raise ValidationError('Integritätsprüfung fehlgeschlagen. Administration verständigen.', code='FILE_INTEGRITY')
        source.seek(0)
        return source
    except OSError as error:
        if source:source.close()
        raise ValidationError('Datei im Speicher nicht verfügbar. Bitte die Administration verständigen.', code='FILE_UNAVAILABLE') from error
    except BaseException:
        if source:source.close()
        raise


def safe_filename(value):
    name = PurePosixPath(str(value).replace('\\','/')).name
    return ''.join(c for c in name if ord(c)>=32 and ord(c)!=127).strip() or 'Dokument'


class DownloadResponse(FileResponse):
    block_size = 64 * 1024


def file_response(source, filename, *, attachment=True, content_type='application/octet-stream'):
    try:
        return DownloadResponse(source, as_attachment=attachment, filename=safe_filename(filename), content_type=content_type)
    except BaseException:
        source.close()
        raise


def failure_response(request, error):
    code = getattr(error, 'code', '')
    allowed = {'FILE_KEY','FILE_UNAVAILABLE','FILE_INTEGRITY','PDF_BUSY','PDF_MEMORY','PDF_TIMEOUT','PDF_RENDER','PDF_FORMAT'}
    if code not in allowed:code = 'FILE_UNAVAILABLE'
    logging.getLogger('dms.download').warning('Download failed', extra={
        'request':request,'event_code':'DOWNLOAD_FAILURE','error_code':code,
    })
    status = 503 if code in {'PDF_BUSY','PDF_MEMORY','PDF_TIMEOUT'} else 409
    message = ' '.join(error.messages)
    request_id = getattr(request, 'diagnostic_id', '')
    if request_id:message += '\nAnfrage-ID: '+request_id
    response = HttpResponse(message, status=status, content_type='text/plain; charset=utf-8')
    if status==503:response['Retry-After'] = '3'
    return response
