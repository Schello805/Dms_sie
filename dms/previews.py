import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from django.core.exceptions import ValidationError
from django.utils import timezone
from . import storage,services as s


def reading_pdf(user,version_id,file_id,url):
    uid,v = s.get_version(user,version_id)
    file,content = storage.download(user,version_id,file_id)
    suffix = Path(file['original_name']).suffix.lower()
    if suffix not in ('.pdf','.txt'):
        raise ValidationError('Für dieses Format bitte eine PDF-Lesefassung im Entwurf hinterlegen. Die Originaldatei kann heruntergeladen werden.')
    approval = s.query("SELECT decided_at FROM approval_decisions WHERE version_id=%s AND stage='APPROVAL' AND decision='ACCEPT' ORDER BY id DESC LIMIT 1",[version_id])
    metadata = {'number':v['number'],'version':f"Version {v['major']}.{v['minor']}",'status':{'DRAFT':'Entwurf','IN_REVIEW':'In Prüfung','PENDING_APPROVAL':'Zur Freigabe','APPROVED':'Freigegeben','ARCHIVED':'Archiviert'}[v['status']],
        'title':v['title'],'approved_on':str(timezone.localtime(approval[0]['decided_at']).date()) if approval else 'nicht freigegeben','url':url,'suffix':suffix}
    with tempfile.TemporaryDirectory(prefix='ims-pdf-') as folder:
        directory = Path(folder)
        source,target,meta = directory/'source',directory/'reading.pdf',directory/'meta.json'
        source.write_bytes(content)
        source.chmod(0o600)
        meta.write_text(json.dumps(metadata))
        meta.chmod(0o600)
        try:
            subprocess.run([sys.executable,str(Path(__file__).with_name('render_reading_pdf.py')),str(source),str(target),str(meta)],
                check=True,timeout=35,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if target.stat().st_size>60*1024*1024:
                raise ValidationError('PDF-Lesefassung überschreitet das Größenlimit.')
            result = target.read_bytes()
        except (subprocess.SubprocessError,OSError):
            raise ValidationError('PDF-Lesefassung konnte nicht erstellt werden. Datei prüfen oder Original herunterladen.')
    s.audit(uid,'PREVIEW_PDF',version_id,'Abgeleitete PDF-Lesefassung erzeugt',{'file_id':file_id,'derived_sha256':hashlib.sha256(result).hexdigest()})
    return v['number']+f"-v{v['major']}.{v['minor']}.pdf",result
