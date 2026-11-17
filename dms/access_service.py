"""Transaction boundary for every document mutation; all SQL uses bound parameters."""
from .audit_text import optional_reason
import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .catalog_columns import CATALOG_SORTS


from . import services as s

def version_history(user, version_id):
    uid,v = s.get_version(user,version_id)
    if not any(s.allowed(uid,v['responsible_department_id'],r,v['document_id']) for r in ('AUTHOR','REVIEWER')):
        raise PermissionDenied('Die Versionshistorie ist auf Dokumentenverantwortliche und Prüfrollen beschränkt.')
    versions = s.query("""SELECT v.*,u.display_name AS author_name,
        (v.id=current_release(v.document_id)) AS current_release
        FROM document_versions v JOIN users u ON u.id=v.created_by
        WHERE v.document_id=%s AND can_read_version(%s,v.id) ORDER BY v.major DESC,v.minor DESC""",[v['document_id'],uid])
    decisions = s.query("""SELECT a.*,u.display_name AS actor_name,w.started_at,w.closed_at
        FROM approval_decisions a JOIN users u ON u.id=a.actor_id
        JOIN workflow_instances w ON w.id=a.workflow_id
        JOIN document_versions v ON v.id=a.version_id
        WHERE v.document_id=%s AND can_read_version(%s,v.id) ORDER BY a.id DESC""",[v['document_id'],uid])
    s.audit(uid,'VIEW_HISTORY',version_id,'Versions- und Freigabehistorie eingesehen')
    return v,versions,decisions

def access_policy(document_id):
    mode = s.query('SELECT access_mode FROM documents WHERE id=%s',[document_id])[0]['access_mode']
    people = s.query('SELECT user_id FROM document_access_users WHERE document_id=%s ORDER BY user_id',[document_id])
    groups = s.query('SELECT group_id FROM document_access_groups WHERE document_id=%s ORDER BY group_id',[document_id])
    return {'access_mode':mode,'users':people,'groups':groups}

@transaction.atomic
def change_access(user,version_id,access_mode,users,groups,reason):
    reason = optional_reason(reason)
    uid,v = s.get_version(user,version_id,lock=True)
    document_id = v['document_id']
    s.require(uid,v['responsible_department_id'],'AUTHOR',document_id)
    s.query('SELECT id FROM documents WHERE id=%s FOR UPDATE',[document_id])
    if access_mode not in ('DEPARTMENT','EXPLICIT'):
        raise ValidationError('Gültigen Zugriffsbereich auswählen.')
    before = s.access_policy(document_id)
    s.query('UPDATE documents SET access_mode=%s WHERE id=%s',[access_mode,document_id])
    for table,column,values in [('document_access_users','user_id',users),('document_access_groups','group_id',groups)]:
        s.query(f'DELETE FROM {table} WHERE document_id=%s',[document_id])
        for value in sorted(set(values)):
            s.query(f'INSERT INTO {table}(document_id,{column}) VALUES (%s,%s)',[document_id,value])
    if not s.query('SELECT can_read_version(%s,%s) AS permitted',[uid,version_id])[0]['permitted']:
        raise ValidationError('Du musst selbst weiterhin berechtigt bleiben. Änderungen wurden nicht gespeichert.')
    s.audit(uid,'CHANGE_ACCESS',version_id,reason,{'document_id':document_id,'before':before,'after':s.access_policy(document_id)})

@transaction.atomic
def lifecycle_action(user,version_id,action,reason,confirmed=False):
    reason = optional_reason(reason)
    uid,v = s.get_version(user,version_id,lock=True)
    from .policies import require_qmb
    require_qmb(user)
    if not confirmed or action not in ('withdraw','archive'):
        raise ValidationError('Gültiger Vorgang und Bestätigung sind erforderlich.')
    s.query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if action=='archive':
        if v['status']!='APPROVED':
            raise ValidationError('Nur freigegebene Fassungen können archiviert werden.')
        s.query("UPDATE document_versions SET status='ARCHIVED' WHERE id=%s",[version_id])
        s.audit(uid,'ARCHIVE',version_id,reason,{'document_id':v['document_id']})
    else:
        released = s.query("SELECT 1 FROM document_versions WHERE document_id=%s AND status='APPROVED'",[v['document_id']])
        if not released:
            raise ValidationError('Das Dokument besitzt keine freigegebene Fassung.')
        latest = s.query('SELECT withdrawn_at FROM document_withdrawals WHERE document_id=%s ORDER BY id DESC LIMIT 1',[v['document_id']])
        if latest and not s.query("SELECT 1 FROM approval_decisions a JOIN document_versions dv ON dv.id=a.version_id WHERE dv.document_id=%s AND a.stage='APPROVAL' AND a.decision='ACCEPT' AND a.decided_at>%s",[v['document_id'],latest[0]['withdrawn_at']]):
            raise ValidationError('Das Dokument ist bereits zurückgezogen.')
        withdrawal = s.query('INSERT INTO document_withdrawals(document_id,actor_id,reason) VALUES (%s,%s,%s) RETURNING id',[v['document_id'],uid,reason])[0]['id']
        s.audit(uid,'WITHDRAW_DOCUMENT',version_id,reason,{'document_id':v['document_id'],'withdrawal_id':withdrawal})
