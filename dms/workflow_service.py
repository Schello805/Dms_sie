"""Transaction boundary for every document mutation; all SQL uses bound parameters."""
from .audit_text import optional_reason
import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .catalog_columns import CATALOG_SORTS


from . import services as s

@transaction.atomic
def transition(user, version_id, action, comment):
    if action=='submit':
        s.query("SELECT pg_advisory_xact_lock(hashtext('ims-master-data'))")
    uid, v = s.get_version(user, version_id, lock=True)
    department = v['responsible_department_id']
    s.query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if not comment.strip():
        raise ValidationError('Eine Begründung ist erforderlich.')
    if action == 'submit':
        s.require(uid, department, 'AUTHOR',v['document_id'])
        if v['status'] != 'DRAFT':
            raise ValidationError('Nur Entwürfe können eingereicht werden.')
        if not s.query('SELECT 1 FROM version_files WHERE version_id=%s',[version_id]):
            raise ValidationError('Mindestens eine Dokumentdatei ist erforderlich.')
        if not v['effective_from']:
            raise ValidationError('Wirksamkeitsdatum fehlt.')
        s.query('INSERT INTO workflow_instances(version_id,content_fingerprint,submitted_by) VALUES (%s,%s,%s)', [version_id,s.fingerprint(v),uid])
        target = 'IN_REVIEW'
    else:
        workflows = s.query('SELECT * FROM workflow_instances WHERE version_id=%s AND closed_at IS NULL FOR UPDATE', [version_id])
        if not workflows:
            raise ValidationError('Kein aktiver Prüfzyklus.')
        w = workflows[0]
        stage = {'IN_REVIEW':'REVIEW','PENDING_APPROVAL':'APPROVAL'}.get(v['status'])
        if not stage or action not in ('accept','return'):
            raise ValidationError('Aktion in diesem Status nicht möglich.')
        from .policies import require_qmb
        if stage=='REVIEW':
            require_qmb(user)
        elif not s.query('SELECT is_qmb(%s) OR can_lead_approve(%s,%s) AS allowed',[uid,uid,version_id])[0]['allowed']:
            raise PermissionDenied('Freigabe erfordert den prüfenden QMB oder die benannte QMB-Abteilungsleitung.')
        if uid in (v['created_by'],w['submitted_by']):
            raise PermissionDenied('Eigene Dokumente dürfen nicht selbst geprüft oder freigegeben werden. Der andere QMB muss übernehmen.')
        if stage=='APPROVAL':
            reviewer = s.query("SELECT actor_id,qmb_role_at_decision FROM approval_decisions WHERE workflow_id=%s AND stage='REVIEW' AND decision='ACCEPT'",[w['id']])
            if reviewer and reviewer[0]['qmb_role_at_decision'] is None:
                raise ValidationError('Bestehenden Altzyklus zuerst neu zur QMB-Prüfung übernehmen.')
            if not reviewer or (reviewer[0]['actor_id']!=uid and not s.query('SELECT can_lead_approve(%s,%s) AS allowed',[uid,version_id])[0]['allowed']):
                raise PermissionDenied('Nur der prüfende QMB darf freigeben. Eine Vertretung muss die Prüfung neu übernehmen.')
        if s.fingerprint(v) != w['content_fingerprint']:
            raise ValidationError('Inhalt stimmt nicht mit dem eingereichten Stand überein.')
        s.query('''INSERT INTO approval_decisions(version_id,actor_id,stage,decision,comment,content_fingerprint,workflow_id,qmb_role_at_decision,approval_lead_at_decision)
            VALUES (%s,%s,%s,%s,%s,%s,%s,(SELECT NULLIF(qmb_role,'NONE') FROM users WHERE id=%s),is_qmb_approval_lead(%s))''', [version_id,uid,stage,'ACCEPT' if action=='accept' else 'RETURN',comment,w['content_fingerprint'],w['id'],uid,uid])
        target = 'DRAFT' if action=='return' else ('PENDING_APPROVAL' if stage=='REVIEW' else 'APPROVED')
    if target=='APPROVED' and v['approval_based_validity']:
        from .policies import add_months,interval_for
        approved_at = s.query("SELECT decided_at FROM approval_decisions WHERE workflow_id=%s AND stage='APPROVAL' AND decision='ACCEPT'",[w['id']])[0]['decided_at']
        months = interval_for(v['document_type'])
        s.query('INSERT INTO release_validity(version_id,approved_at,review_due_on,interval_months) VALUES (%s,%s,%s,%s)',[version_id,approved_at,add_months(timezone.localtime(approved_at).date(),months),months])
    s.query('UPDATE document_versions SET status=%s WHERE id=%s', [target,version_id])
    if target in ('DRAFT','APPROVED'):
        s.query('UPDATE workflow_instances SET closed_at=clock_timestamp() WHERE version_id=%s AND closed_at IS NULL', [version_id])
    s.audit(uid, 'TRANSITION', version_id, comment, {'from':v['status'],'to':target})
    if target=='APPROVED':
        from .portal import synchronize_acknowledgements
        synchronize_acknowledgements()

@transaction.atomic
def record_review(user, version_id, result, rationale, next_review_on=None):
    rationale = optional_reason(rationale)
    uid,v = s.get_version(user,version_id,lock=True)
    from .policies import require_qmb
    require_qmb(user)
    if uid == v['created_by']:
        raise PermissionDenied('Die periodische Prüfung muss unabhängig vom Ersteller erfolgen.')
    if v['status']!='APPROVED' or s.query('SELECT current_release(%s) AS id',[v['document_id']])[0]['id'] != version_id:
        raise ValidationError('Nur die aktuell wirksame freigegebene Fassung kann geprüft werden.')
    if result not in ('UNCHANGED','REVISION_REQUIRED','WITHDRAWAL_REQUIRED'):
        raise ValidationError('Gültiges Prüfergebnis auswählen.')
    from .policies import interval_for,add_months
    months = interval_for(v['document_type'])
    if result=='UNCHANGED' and next_review_on is None:
        next_review_on = add_months(timezone.localdate(),months)
    if result=='UNCHANGED' and next_review_on>add_months(timezone.localdate(),months):
        raise ValidationError('Der Prüftermin darf die Gültigkeit der Kategorie nicht überschreiten.')
    if next_review_on and next_review_on<=timezone.localdate():
        raise ValidationError('Der neue Prüftermin muss in der Zukunft liegen.')
    review = s.query('INSERT INTO periodic_reviews(version_id,reviewer_id,result,rationale,next_review_on,review_interval_months) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',[version_id,uid,result,rationale,next_review_on,months])[0]['id']
    s.audit(uid,'PERIODIC_REVIEW',version_id,rationale,{'review_id':review,'result':result,'review_interval_months':months,'next_review_on':str(next_review_on) if next_review_on else None})
    return review

def workflow_tasks(user):
    uid = s.actor(user)
    return s.query("""SELECT v.id,v.document_id,v.title,v.major,v.minor,v.status,d.number,w.started_at,
        CASE WHEN v.status='IN_REVIEW' THEN 'QMB-Prüfung' ELSE 'Freigabe nach QMB-Prüfung' END AS task_label
        FROM document_versions v JOIN documents d ON d.id=v.document_id
        JOIN workflow_instances w ON w.version_id=v.id AND w.closed_at IS NULL
        WHERE d.active AND (is_qmb(%s) OR can_lead_approve(%s,v.id)) AND can_read_version(%s,v.id)
          AND v.created_by<>%s AND w.submitted_by<>%s
          AND v.status IN ('IN_REVIEW','PENDING_APPROVAL')
        ORDER BY w.started_at,v.id LIMIT 5000""",[uid,uid,uid,uid,uid])

@transaction.atomic
def takeover_review(user,version_id,reason):
    reason = optional_reason(reason)
    from .policies import require_qmb
    uid = require_qmb(user)
    _,v = s.get_version(user,version_id,lock=True)
    s.query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if v['status']!='PENDING_APPROVAL' or uid==v['created_by']:
        raise ValidationError('Übernahme erfordert eine fremde, bereits geprüfte Fassung.')
    w = s.query('SELECT * FROM workflow_instances WHERE version_id=%s AND closed_at IS NULL FOR UPDATE',[version_id])[0]
    if uid==w['submitted_by']:
        raise PermissionDenied('Der Einreicher kann die Prüfung nicht selbst übernehmen.')
    s.query('UPDATE workflow_instances SET closed_at=clock_timestamp() WHERE id=%s',[w['id']])
    s.query("UPDATE document_versions SET status='DRAFT' WHERE id=%s",[version_id])
    s.query('INSERT INTO workflow_instances(version_id,content_fingerprint,submitted_by) VALUES (%s,%s,%s)',[version_id,s.fingerprint(v),w['submitted_by']])
    s.query("UPDATE document_versions SET status='IN_REVIEW' WHERE id=%s",[version_id])
    s.audit(uid,'QMB_TAKEOVER',version_id,reason,{'previous_workflow_id':w['id']})
