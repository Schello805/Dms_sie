"""One upload, one QMB decision; legacy immutable review decisions remain auditable."""
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from . import services as s,storage
from .policies import require_qmb


def upload_document(user,data,uploaded,submit=False):
    paths = []
    try:
        with transaction.atomic():
            metadata = dict(data,approval_based_validity=True)
            vid = s.create_document(user,metadata)
            storage.upload(user,vid,uploaded)
            from django.conf import settings
            paths = [settings.MEDIA_ROOT/f['storage_key'] for f in s.query('SELECT f.storage_key FROM file_objects f JOIN version_files vf ON vf.file_id=f.id WHERE vf.version_id=%s',[vid])]
            if submit:
                s.transition(user,vid,'submit','Autor hat die Freigabe angefordert.')
            return vid
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise


@transaction.atomic
def decide(user,version_id,approve,comment):
    uid = require_qmb(user)
    _,v = s.get_version(user,version_id,lock=True)
    if uid==v['created_by']:
        raise PermissionDenied('Eigene Dokumente dürfen nicht selbst freigegeben werden.')
    if v['status'] not in ('IN_REVIEW','PENDING_APPROVAL'):
        raise ValidationError('Für diese Fassung liegt keine offene Freigabeanfrage vor.')
    if not approve and not comment.strip():
        raise ValidationError('Bei Ablehnung ist eine Bemerkung für den Autor erforderlich.')
    comment = comment.strip() or 'Nach fachlicher Prüfung freigegeben.'
    if v['status']=='PENDING_APPROVAL':
        reviewer = s.query("SELECT a.actor_id,a.qmb_role_at_decision FROM approval_decisions a JOIN workflow_instances w ON w.id=a.workflow_id WHERE w.version_id=%s AND w.closed_at IS NULL AND a.stage='REVIEW' AND a.decision='ACCEPT'",[version_id])
        if not reviewer or reviewer[0]['actor_id']!=uid or not reviewer[0]['qmb_role_at_decision']:
            s.takeover_review(user,version_id,'Freigabeanfrage zur eigenen QMB-Prüfung übernommen.')
            v['status']='IN_REVIEW'
    s.transition(user,version_id,'accept' if approve else 'return',comment)
    if approve and v['status']=='IN_REVIEW':
        s.transition(user,version_id,'accept',comment)
    if approve and not s.query('SELECT 1 FROM release_validity WHERE version_id=%s',[version_id]):
        from django.utils import timezone
        from .policies import add_months,interval_for
        approved_at = s.query("SELECT max(decided_at) AS at FROM approval_decisions WHERE version_id=%s AND stage='APPROVAL' AND decision='ACCEPT'",[version_id])[0]['at']
        months = interval_for(v['document_type'])
        s.query('INSERT INTO release_validity(version_id,approved_at,review_due_on,interval_months) VALUES (%s,%s,%s,%s)',[version_id,approved_at,add_months(timezone.localtime(approved_at).date(),months),months])


def returned_tasks(user):
    uid = s.actor(user)
    return s.query('''SELECT v.id,v.title,v.major,v.minor,d.number,a.comment,a.decided_at
        FROM document_versions v JOIN documents d ON d.id=v.document_id
        JOIN LATERAL (SELECT x.comment,x.decided_at FROM approval_decisions x WHERE x.version_id=v.id
          AND x.decision='RETURN' ORDER BY x.id DESC LIMIT 1) a ON true
        WHERE v.created_by=%s AND v.status='DRAFT' AND can_read_version(%s,v.id)
        AND has_role(%s,'AUTHOR',d.responsible_department_id,d.id) ORDER BY a.decided_at DESC''',[uid,uid,uid])


def open_reading_copy(request,version_id):
    from pathlib import Path
    from django.shortcuts import redirect
    s.get_version(request.user,version_id)
    files = s.query("SELECT f.id,f.original_name FROM version_files vf JOIN file_objects f ON f.id=vf.file_id WHERE vf.version_id=%s ORDER BY CASE WHEN vf.purpose='RELEASE' THEN 0 WHEN lower(f.original_name) LIKE '%%.pdf' THEN 1 WHEN lower(f.original_name) LIKE '%%.txt' THEN 2 ELSE 3 END,f.id LIMIT 1",[version_id])
    if not files:
        raise PermissionDenied('Keine Lesefassung verfügbar.')
    file = files[0]
    return redirect('pdf_viewer' if Path(file['original_name']).suffix.lower() in ('.pdf','.txt') else 'download',version_id=version_id,file_id=file['id'])
