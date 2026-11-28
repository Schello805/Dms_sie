"""Generate private derived PDFs without buffering source or result in the web worker."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from django.core.exceptions import ValidationError
from django.utils import timezone
from . import storage, services as s
from .file_delivery import CHUNK_BYTES
from .preview_resources import render_slot


MAX_TEXT_PREVIEW_BYTES = 1024 * 1024


def is_previewable(file):
    suffix = Path(file['original_name']).suffix.lower()
    return suffix == '.pdf' or (suffix == '.txt' and file['size_bytes'] <= MAX_TEXT_PREVIEW_BYTES)


def open_reading_pdf(user, version_id, file_id, url):
    from .public_reading import get_read_version
    uid,v = get_read_version(user,version_id)
    result = None
    try:
        with render_slot() as memory, tempfile.TemporaryDirectory(prefix='ims-pdf-') as folder:
            file,source = storage.open_download(user,version_id,file_id,public=True)
            suffix = Path(file['original_name']).suffix.lower()
            with source:
                if suffix not in ('.pdf','.txt'):
                    raise ValidationError('Für dieses Format bitte eine PDF-Lesefassung hinterlegen oder das Original herunterladen.', code='PDF_FORMAT')
                if suffix=='.txt' and file['size_bytes']>MAX_TEXT_PREVIEW_BYTES:
                    raise ValidationError('Für große Textdateien bitte das Original herunterladen.', code='PDF_FORMAT')
                directory = Path(folder)
                original,target,meta = directory/'source',directory/'reading.pdf',directory/'meta.json'
                with original.open('wb') as destination:
                    shutil.copyfileobj(source,destination,length=64*1024)
                original.chmod(0o600)
            approval = s.query("SELECT decided_at FROM approval_decisions WHERE version_id=%s AND stage='APPROVAL' AND decision='ACCEPT' ORDER BY id DESC LIMIT 1",[version_id])
            metadata = {'number':v['number'],'version':f"Version {v['major']}.{v['minor']}",
                'status':{'DRAFT':'Entwurf','IN_REVIEW':'In Prüfung','PENDING_APPROVAL':'Zur Freigabe','APPROVED':'Freigegeben','ARCHIVED':'Archiviert'}[v['status']],
                'title':v['title'],'approved_on':str(timezone.localtime(approval[0]['decided_at']).date()) if approval else 'nicht freigegeben',
                'url':url,'suffix':suffix}
            meta.write_text(json.dumps(metadata))
            meta.chmod(0o600)
            environment = {key:value for key,value in os.environ.items() if key in ('PATH','LANG','LC_ALL','SYSTEMROOT')}
            environment.update(PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
            try:
                subprocess.run([sys.executable,str(Path(__file__).with_name('render_reading_pdf.py')),str(original),str(target),str(meta),str(memory)],
                    check=True,timeout=35,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=environment)
            except subprocess.TimeoutExpired as error:
                raise ValidationError('Die PDF-Erstellung hat das Zeitlimit erreicht. Bitte das Original herunterladen.',code='PDF_TIMEOUT') from error
            except subprocess.CalledProcessError as error:
                raise ValidationError('PDF-Lesefassung konnte nicht erstellt werden. Bitte das Original herunterladen; die Datei kann beschädigt oder zu komplex sein.',code='PDF_RENDER') from error
            if not 0<target.stat().st_size<=60*1024*1024:
                raise ValidationError('PDF-Lesefassung überschreitet das Größenlimit. Bitte das Original herunterladen.',code='PDF_FORMAT')
            result = target.open('rb')
            digest = hashlib.sha256()
            while chunk := result.read(CHUNK_BYTES):
                digest.update(chunk)
            result.seek(0)
            s.audit(uid,'PREVIEW_PDF',version_id,'Abgeleitete PDF-Lesefassung erzeugt',{'file_id':file_id,'derived_sha256':digest.hexdigest()})
        # POSIX: the private work directory is removed, while this descriptor remains
        # readable until FileResponse closes it. No generated files accumulate.
        return v['number']+f"-v{v['major']}.{v['minor']}.pdf",result
    except OSError as error:
        if result:result.close()
        raise ValidationError('PDF-Lesefassung konnte nicht bereitgestellt werden. Bitte das Original herunterladen.',code='PDF_RENDER') from error
    except BaseException:
        if result:result.close()
        raise


def reading_pdf(user, version_id, file_id, url):
    """Compatibility API for callers needing bytes; HTTP uses open_reading_pdf."""
    filename,source = open_reading_pdf(user,version_id,file_id,url)
    with source:
        return filename,source.read()
