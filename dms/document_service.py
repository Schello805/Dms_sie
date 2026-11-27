from .validity import validity_start
"""Transaction boundary for every document mutation; all SQL uses bound parameters."""
from .audit_text import optional_reason
import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .catalog_columns import CATALOG_SORTS


from . import services as s

def load_version(version_id,lock=False):
    rows = s.query('''SELECT v.*,d.active AS document_active,d.login_required,d.number,d.document_type,d.owner_id,(SELECT display_name FROM users WHERE id=d.owner_id) AS owner_name,d.responsible_department_id,c.review_interval_months,coalesce(c.display_name,c.name) AS category_label,review.review_due_on,review.last_review_on,(SELECT uploaded_at FROM document_upload_origins WHERE document_id=v.document_id) AS uploaded_at,(SELECT max(a.decided_at) FROM approval_decisions a WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT') AS approved_at FROM document_versions v
                    JOIN documents d ON d.id=v.document_id
                    JOIN document_categories c ON c.name=d.document_type
                    JOIN version_review_status review ON review.version_id=v.id WHERE v.id=%s''' + (' FOR UPDATE OF v' if lock else ''), [version_id])
    if not rows:
        raise PermissionDenied('Dokument nicht verfügbar.')
    return rows[0]

def get_version(user, version_id, lock=False):
    uid = s.actor(user)
    v = load_version(version_id,lock)
    if lock and not v['document_active']:
        raise PermissionDenied('Deaktivierte Dokumente müssen zuerst durch den QMB reaktiviert werden.')
    if not s.query('SELECT can_read_version(%s,%s) AS permitted',[uid,version_id])[0]['permitted']:
        raise PermissionDenied('Dokument nicht verfügbar.')
    return uid, v

@transaction.atomic
def create_document(user, data):
    data = dict(data,change_summary=optional_reason(data.get('change_summary')),effective_from=validity_start(data.get('effective_from')))
    s.query("SELECT pg_advisory_xact_lock(hashtext('ims-master-data'))")
    uid = s.actor(user)
    department = data['department']
    s.require(uid, department, 'AUTHOR')
    if not s.query('SELECT 1 FROM departments WHERE id=%s AND active',[department]):
        raise ValidationError('Für neue Dokumente eine aktive Abteilung auswählen.')
    if not s.query('SELECT 1 FROM document_categories WHERE name=%s AND active',[data['document_type']]):
        raise ValidationError('Für neue Dokumente eine aktive Kategorie auswählen.')
    if not str(data.get('number') or '').strip():
        raise ValidationError('Eine Dokumentnummer ist erforderlich.')
    data['number']=data['number'].strip()
    from .policies import default_due
    review_due = data.get('next_review_on') or default_due(data['document_type'],data.get('effective_from'))
    doc = s.query('''INSERT INTO documents(number,document_type,owner_id,responsible_department_id)
        VALUES (%s,%s,%s,%s) RETURNING id''', [data['number'],data['document_type'],uid,department])[0]['id']
    vid = s.query('''INSERT INTO document_versions(document_id,major,minor,title,change_summary,created_by,effective_from,next_review_on,classification)
        VALUES (%s,1,0,%s,%s,%s,%s,%s,%s) RETURNING id''', [doc,data['title'],data['change_summary'],uid,data['effective_from'],review_due,data.get('classification','INTERNAL')])[0]['id']
    if data.get('approval_based_validity'):
        s.query('UPDATE document_versions SET approval_based_validity=true WHERE id=%s',[vid])
    s.query('INSERT INTO document_access_users VALUES (%s,%s)',[doc,uid])
    s.query('INSERT INTO version_departments VALUES (%s,%s)', [vid,department])
    s.save_mappings(vid,department,data)
    s.audit(uid, 'CREATE', vid, data['change_summary'])
    return vid

@transaction.atomic
def edit_draft(user, version_id, data):
    data = dict(data,change_summary=optional_reason(data.get('change_summary')),effective_from=validity_start(data.get('effective_from')))
    uid, v = s.get_version(user, version_id, lock=True)
    s.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] != 'DRAFT':
        raise ValidationError('Nur Entwürfe können bearbeitet werden.')
    from .policies import default_due
    review_due = data.get('next_review_on') or default_due(v['document_type'],data.get('effective_from'))
    s.query('''UPDATE document_versions SET title=%s,change_summary=%s,effective_from=%s,next_review_on=%s,classification=%s
        WHERE id=%s''',[data['title'],data['change_summary'],data['effective_from'],review_due,data.get('classification',v['classification']),version_id])
    if not s.query('SELECT can_read_version(%s,%s) AS permitted',[uid,version_id])[0]['permitted']:
        raise ValidationError('Vor einer vertraulichen Einstufung musst du im Dokumentzugriff ausdrücklich berechtigt sein.')
    s.save_mappings(version_id,v['responsible_department_id'],data)
    s.audit(uid,'EDIT',version_id,data['change_summary'])

@transaction.atomic
def new_revision(user, version_id, kind='major', reason='Neue Überarbeitung'):
    reason = optional_reason(reason)
    uid, v = s.get_version(user, version_id, lock=True)
    s.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] not in ('APPROVED','ARCHIVED'):
        raise ValidationError('Eine neue Revision setzt eine bereits freigegebene Ausgangsversion voraus.')
    if kind not in ('major','minor'):
        raise ValidationError('Gültige Versionsart auswählen.')
    # Serialize numbering for all versions of the same document.
    s.query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if s.query("SELECT 1 FROM document_versions WHERE document_id=%s AND status IN ('DRAFT','IN_REVIEW','PENDING_APPROVAL')",[v['document_id']]):
        raise ValidationError('Es gibt bereits eine laufende Überarbeitung.')
    latest = s.query("SELECT id FROM document_versions WHERE document_id=%s AND status IN ('APPROVED','ARCHIVED') ORDER BY major DESC,minor DESC LIMIT 1",[v['document_id']])[0]['id']
    if latest != version_id:
        raise ValidationError('Die Überarbeitung muss von der neuesten freigegebenen Version ausgehen.')
    if kind=='major':
        major = s.query('SELECT max(major)+1 AS major FROM document_versions WHERE document_id=%s',[v['document_id']])[0]['major']
        minor = 0
    else:
        major = v['major']
        minor = s.query('SELECT max(minor)+1 AS minor FROM document_versions WHERE document_id=%s AND major=%s',[v['document_id'],major])[0]['minor']
    vid = s.query('''INSERT INTO document_versions(document_id,major,minor,title,change_summary,created_by,classification,next_review_on,effective_from)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',[v['document_id'],major,minor,v['title'],reason,uid,v['classification'],v['next_review_on'],validity_start(timezone.now())])[0]['id']
    for table, column in [('version_departments','department_id'),('version_standard_links','reference_id')]:
        # Table/column names come exclusively from these constants.
        s.query(f'INSERT INTO {table}(version_id,{column}) SELECT %s,{column} FROM {table} WHERE version_id=%s',[vid,version_id])
    s.query('INSERT INTO version_files(version_id,file_id,purpose) SELECT %s,file_id,purpose FROM version_files WHERE version_id=%s',[vid,version_id])
    s.query('UPDATE document_versions SET approval_based_validity=true WHERE id=%s',[vid])
    s.query('INSERT INTO version_distribution(version_id,change_kind,requires_ack,ack_days,keywords) SELECT %s,change_kind,requires_ack,ack_days,keywords FROM version_distribution WHERE version_id=%s',[vid,version_id])
    s.query('INSERT INTO version_audiences(version_id,audience_id) SELECT %s,audience_id FROM version_audiences WHERE version_id=%s',[vid,version_id])
    s.audit(uid,'CREATE_REVISION',vid,reason,{'source_version':version_id,'kind':kind,'version':f'{major}.{minor}'})
    return vid

@transaction.atomic
def remove_file(user, version_id, file_id, reason):
    reason = optional_reason(reason)
    uid,v = s.get_version(user,version_id,lock=True)
    s.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] != 'DRAFT':
        raise ValidationError('Dateien können nur im Entwurf entfernt werden.')
    if not s.query('SELECT 1 FROM version_files WHERE version_id=%s AND file_id=%s',[version_id,file_id]):
        raise ValidationError('Datei gehört nicht zu diesem Entwurf.')
    s.query('DELETE FROM version_files WHERE version_id=%s AND file_id=%s',[version_id,file_id])
    s.audit(uid,'UNLINK_FILE',version_id,reason,{'file_id':file_id})

def save_mappings(version_id, department, data):
    # Called only inside a locked draft transaction by create_document/edit_draft.
    for key,table,column in [('applicable_departments','version_departments','department_id'),('standard_references','version_standard_links','reference_id')]:
        if key not in data:
            continue
        values = set(data[key])
        if key=='applicable_departments':
            values.add(department)
        existing = {row[column] for row in s.query(f'SELECT {column} FROM {table} WHERE version_id=%s',[version_id])}
        additions = values-existing
        if key=='standard_references' and additions and len(s.query('SELECT r.id FROM standard_references r JOIN standards s ON s.id=r.standard_id WHERE r.id=ANY(%s::bigint[]) AND r.active AND s.active',[list(additions)])) != len(additions):
            raise ValidationError('Nur aktive Normreferenzen dürfen neu zugeordnet werden.')
        if key=='applicable_departments' and additions and len(s.query('SELECT id FROM departments WHERE id=ANY(%s::bigint[]) AND active',[list(additions)])) != len(additions):
            raise ValidationError('Nur aktive Abteilungen dürfen neu zugeordnet werden.')
        if existing-values:
            s.query(f'DELETE FROM {table} WHERE version_id=%s AND {column}=ANY(%s::bigint[])',[version_id,list(existing-values)])
        for value in sorted(additions):
            s.query(f'INSERT INTO {table}(version_id,{column}) VALUES (%s,%s)',[version_id,value])
