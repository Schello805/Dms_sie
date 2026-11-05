"""Transaction boundary for every document mutation; all SQL uses bound parameters."""
import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .catalog_columns import CATALOG_SORTS


def query(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        if cursor.description:
            return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
        return []


def actor(user):
    rows = query('SELECT id FROM users WHERE auth_user_id=%s AND active', [user.pk])
    if not user.is_active or not rows:
        raise PermissionDenied('Kein aktives DMS-Konto zugeordnet.')
    return rows[0]['id']


def allowed(uid, department, role, document_id=None):
    return query('SELECT has_role(%s,%s,%s,%s) AS allowed',[uid,role,department,document_id])[0]['allowed']


def require(uid, department, role, document_id=None):
    if not allowed(uid,department,role,document_id):
        raise PermissionDenied('Erforderliche Rolle fehlt: ' + role)


def audit(uid, action, version_id, reason, details=None):
    query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,%s,'version',%s,%s,%s::jsonb)", [uid, action, str(version_id), reason, json.dumps(details or {})])



def visible_versions(user, search='', status='', department='', standard='', due_only=False, current_only=False, limit=200, catalog_only=False, offset=0, sort='', direction='asc'):
    uid = actor(user) if user.is_authenticated else None
    search = search.strip()[:200]
    pattern = '%' + search + '%'
    if catalog_only and status not in ('','DRAFT','APPROVED'):
        return []
    # SQL identifiers and direction come exclusively from this allowlist.
    ordering = (CATALOG_SORTS[sort] + (' DESC' if direction=='desc' else ' ASC') +
        ' NULLS LAST,d.number,v.major DESC,v.minor DESC,v.id') if sort in CATALOG_SORTS else 'COALESCE(matched.score,0) DESC,d.number,v.major DESC,v.minor DESC,v.id'
    rows = query("""WITH input AS (
            SELECT CASE WHEN %s='' THEN NULL::tsquery ELSE websearch_to_tsquery('german',%s) END AS terms
        ) SELECT v.*,count(*) OVER() AS total_count,d.number,dep.name AS department,
        review.review_due_on,review.last_review_on,
        (SELECT uploaded_at FROM document_upload_origins WHERE document_id=v.document_id) AS uploaded_at,
        (SELECT coalesce(rv.approved_at,(SELECT max(a.decided_at) FROM approval_decisions a WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT')) FROM document_versions ignored LEFT JOIN release_validity rv ON rv.version_id=ignored.id WHERE ignored.id=v.id) AS approved_at,
        (v.id=current_release(v.document_id)) AS is_current,
        c.name AS category_name,
        preferred.file_id AS reading_file_id,preferred.original_name AS reading_file_name,
        review.review_result,matched.snippet,matched.original_name AS matched_file,
        (SELECT max(a.decided_at) FROM approval_decisions a WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT') AS released_at,
        (EXISTS (SELECT 1 FROM document_withdrawals dw WHERE dw.document_id=v.document_id)
            AND current_release(v.document_id) IS NULL) AS document_withdrawn
        FROM document_versions v CROSS JOIN input
        JOIN documents d ON d.id=v.document_id
        JOIN departments dep ON dep.id=d.responsible_department_id
        JOIN document_categories c ON c.name=d.document_type
        JOIN version_review_status review ON review.version_id=v.id
        LEFT JOIN LATERAL (SELECT f.id AS file_id,f.original_name FROM version_files vf JOIN file_objects f ON f.id=vf.file_id
            WHERE vf.version_id=v.id ORDER BY CASE WHEN vf.purpose='RELEASE' THEN 0 WHEN lower(f.original_name) LIKE '%%.pdf' THEN 1 WHEN lower(f.original_name) LIKE '%%.txt' THEN 2 ELSE 3 END,f.id LIMIT 1) preferred ON true
        LEFT JOIN LATERAL (
            SELECT i.file_id,f.original_name,ts_rank_cd(i.search_vector,input.terms) AS score,
                left(ts_headline('german',i.text_content,input.terms,
                    'StartSel=[, StopSel=], MaxWords=35, MinWords=10, MaxFragments=1'),600) AS snippet
            FROM version_files vf JOIN file_text_indexes i ON i.file_id=vf.file_id
            JOIN file_objects f ON f.id=vf.file_id
            WHERE vf.version_id=v.id AND (can_read_version(%s,v.id) OR (%s::bigint IS NULL AND d.access_mode='DEPARTMENT' AND v.classification='PUBLIC' AND v.status='APPROVED' AND v.id=current_release(v.document_id)))
                AND i.status='READY' AND i.search_vector @@ input.terms
            ORDER BY score DESC,i.file_id LIMIT 1
        ) matched ON true
        WHERE (can_read_version(%s,v.id) OR (%s::bigint IS NULL AND d.access_mode='DEPARTMENT' AND v.classification='PUBLIC' AND v.status='APPROVED' AND v.id=current_release(v.document_id)))
        AND (%s='' OR v.title ILIKE %s OR d.number ILIKE %s OR matched.file_id IS NOT NULL OR EXISTS(SELECT 1 FROM version_distribution dist WHERE dist.version_id=v.id AND dist.keywords ILIKE %s))
        AND (%s='' OR v.status=%s OR (%s AND %s='DRAFT' AND v.status IN ('IN_REVIEW','PENDING_APPROVAL')))
        AND (NOT %s OR (
            (v.status='APPROVED' AND v.id=current_release(v.document_id))
            OR (v.status IN ('DRAFT','IN_REVIEW','PENDING_APPROVAL') AND v.created_by=%s
                AND has_role(%s,'AUTHOR',d.responsible_department_id,d.id))))
        AND (%s='' OR dep.id::text=%s)
        AND (%s='' OR EXISTS (SELECT 1 FROM version_standard_links vl
            JOIN standard_references sr ON sr.id=vl.reference_id
            WHERE vl.version_id=v.id AND sr.standard_id::text=%s))
        AND (NOT %s OR (v.id=current_release(v.document_id)
           
            AND (review.review_due_on<=%s
                OR review.review_result IN ('REVISION_REQUIRED','WITHDRAWAL_REQUIRED'))))
        AND (NOT %s OR (v.id=current_release(v.document_id) AND v.status='APPROVED'))
        ORDER BY """ + ordering + """ LIMIT %s OFFSET %s""",
        [search,search,uid,uid,uid,uid,search,pattern,pattern,pattern,status,status,catalog_only,status,catalog_only,uid,uid,department,department,
         standard,standard,due_only,timezone.localdate(),current_only,min(max(int(limit),1),5000),max(int(offset),0)])
    for row in rows:
        from pathlib import Path
        row['previewable'] = bool(row['reading_file_name'] and Path(row['reading_file_name']).suffix.lower() in ('.pdf','.txt'))
        row['review_overdue'] = bool(row['is_current'] and row['review_due_on'] and row['review_due_on']<=timezone.localdate())
    return rows


def get_version(user, version_id, lock=False):
    uid = actor(user)
    rows = query('''SELECT v.*,d.number,d.document_type,d.owner_id,(SELECT display_name FROM users WHERE id=d.owner_id) AS owner_name,d.responsible_department_id,c.review_interval_months,review.review_due_on,review.last_review_on,(SELECT uploaded_at FROM document_upload_origins WHERE document_id=v.document_id) AS uploaded_at,(SELECT max(a.decided_at) FROM approval_decisions a WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT') AS approved_at FROM document_versions v
                    JOIN documents d ON d.id=v.document_id
                    JOIN document_categories c ON c.name=d.document_type
                    JOIN version_review_status review ON review.version_id=v.id WHERE v.id=%s''' + (' FOR UPDATE OF v' if lock else ''), [version_id])
    if not rows:
        raise PermissionDenied('Dokument nicht verfügbar.')
    v = rows[0]
    if not query('SELECT can_read_version(%s,%s) AS permitted',[uid,version_id])[0]['permitted']:
        raise PermissionDenied('Dokument nicht verfügbar.')
    return uid, v


def fingerprint(v):
    payload = {k: v[k] for k in ('id','document_id','major','minor','title','change_summary','classification','effective_from','valid_until','next_review_on')}
    payload['files'] = query('''SELECT f.id,f.sha256,f.size_bytes,vf.purpose FROM version_files vf
        JOIN file_objects f ON f.id=vf.file_id WHERE vf.version_id=%s ORDER BY f.id''', [v['id']])
    payload['departments'] = query('SELECT department_id FROM version_departments WHERE version_id=%s ORDER BY department_id', [v['id']])
    payload['standards'] = query('SELECT reference_id FROM version_standard_links WHERE version_id=%s ORDER BY reference_id', [v['id']])
    distribution = query('SELECT change_kind,requires_ack,ack_days,keywords FROM version_distribution WHERE version_id=%s',[v['id']])
    if distribution:
        payload['distribution'] = distribution[0]
        payload['audiences'] = query('SELECT audience_id FROM version_audiences WHERE version_id=%s ORDER BY audience_id',[v['id']])
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


@transaction.atomic
def create_document(user, data):
    uid = actor(user)
    department = data['department']
    require(uid, department, 'AUTHOR')
    from .policies import default_due
    review_due = data.get('next_review_on') or default_due(data['document_type'],data.get('effective_from'))
    doc = query('''INSERT INTO documents(number,document_type,owner_id,responsible_department_id)
        VALUES (%s,%s,%s,%s) RETURNING id''', [data['number'],data['document_type'],uid,department])[0]['id']
    vid = query('''INSERT INTO document_versions(document_id,major,minor,title,change_summary,created_by,effective_from,next_review_on,classification)
        VALUES (%s,1,0,%s,%s,%s,%s,%s,%s) RETURNING id''', [doc,data['title'],data['change_summary'],uid,data['effective_from'],review_due,data.get('classification','INTERNAL')])[0]['id']
    if data.get('approval_based_validity'):
        query('UPDATE document_versions SET approval_based_validity=true WHERE id=%s',[vid])
    query('INSERT INTO document_access_users VALUES (%s,%s)',[doc,uid])
    query('INSERT INTO version_departments VALUES (%s,%s)', [vid,department])
    save_mappings(vid,department,data)
    audit(uid, 'CREATE', vid, data['change_summary'])
    return vid


@transaction.atomic
def transition(user, version_id, action, comment):
    uid, v = get_version(user, version_id, lock=True)
    department = v['responsible_department_id']
    query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if not comment.strip():
        raise ValidationError('Eine Begründung ist erforderlich.')
    if action == 'submit':
        require(uid, department, 'AUTHOR',v['document_id'])
        if v['status'] != 'DRAFT':
            raise ValidationError('Nur Entwürfe können eingereicht werden.')
        if not query('SELECT 1 FROM version_files WHERE version_id=%s',[version_id]):
            raise ValidationError('Mindestens eine Dokumentdatei ist erforderlich.')
        if not v['effective_from']:
            raise ValidationError('Wirksamkeitsdatum fehlt.')
        query('INSERT INTO workflow_instances(version_id,content_fingerprint,submitted_by) VALUES (%s,%s,%s)', [version_id,fingerprint(v),uid])
        target = 'IN_REVIEW'
    else:
        workflows = query('SELECT * FROM workflow_instances WHERE version_id=%s AND closed_at IS NULL FOR UPDATE', [version_id])
        if not workflows:
            raise ValidationError('Kein aktiver Prüfzyklus.')
        w = workflows[0]
        stage = {'IN_REVIEW':'REVIEW','PENDING_APPROVAL':'APPROVAL'}.get(v['status'])
        if not stage or action not in ('accept','return'):
            raise ValidationError('Aktion in diesem Status nicht möglich.')
        from .policies import require_qmb
        if stage=='REVIEW':
            require_qmb(user)
        elif not query('SELECT is_qmb(%s) OR can_lead_approve(%s,%s) AS allowed',[uid,uid,version_id])[0]['allowed']:
            raise PermissionDenied('Freigabe erfordert den prüfenden QMB oder die benannte QMB-Abteilungsleitung.')
        if uid in (v['created_by'],w['submitted_by']):
            raise PermissionDenied('Eigene Dokumente dürfen nicht selbst geprüft oder freigegeben werden. Der andere QMB muss übernehmen.')
        if stage=='APPROVAL':
            reviewer = query("SELECT actor_id,qmb_role_at_decision FROM approval_decisions WHERE workflow_id=%s AND stage='REVIEW' AND decision='ACCEPT'",[w['id']])
            if reviewer and reviewer[0]['qmb_role_at_decision'] is None:
                raise ValidationError('Bestehenden Altzyklus zuerst neu zur QMB-Prüfung übernehmen.')
            if not reviewer or (reviewer[0]['actor_id']!=uid and not query('SELECT can_lead_approve(%s,%s) AS allowed',[uid,version_id])[0]['allowed']):
                raise PermissionDenied('Nur der prüfende QMB darf freigeben. Eine Vertretung muss die Prüfung neu übernehmen.')
        if fingerprint(v) != w['content_fingerprint']:
            raise ValidationError('Inhalt stimmt nicht mit dem eingereichten Stand überein.')
        query('''INSERT INTO approval_decisions(version_id,actor_id,stage,decision,comment,content_fingerprint,workflow_id,qmb_role_at_decision,approval_lead_at_decision)
            VALUES (%s,%s,%s,%s,%s,%s,%s,(SELECT NULLIF(qmb_role,'NONE') FROM users WHERE id=%s),is_qmb_approval_lead(%s))''', [version_id,uid,stage,'ACCEPT' if action=='accept' else 'RETURN',comment,w['content_fingerprint'],w['id'],uid,uid])
        target = 'DRAFT' if action=='return' else ('PENDING_APPROVAL' if stage=='REVIEW' else 'APPROVED')
    if target=='APPROVED' and v['approval_based_validity']:
        from .policies import add_months,interval_for
        approved_at = query("SELECT decided_at FROM approval_decisions WHERE workflow_id=%s AND stage='APPROVAL' AND decision='ACCEPT'",[w['id']])[0]['decided_at']
        months = interval_for(v['document_type'])
        query('INSERT INTO release_validity(version_id,approved_at,review_due_on,interval_months) VALUES (%s,%s,%s,%s)',[version_id,approved_at,add_months(timezone.localtime(approved_at).date(),months),months])
    query('UPDATE document_versions SET status=%s WHERE id=%s', [target,version_id])
    if target in ('DRAFT','APPROVED'):
        query('UPDATE workflow_instances SET closed_at=clock_timestamp() WHERE version_id=%s AND closed_at IS NULL', [version_id])
    audit(uid, 'TRANSITION', version_id, comment, {'from':v['status'],'to':target})
    if target=='APPROVED':
        from .portal import synchronize_acknowledgements
        synchronize_acknowledgements()


@transaction.atomic
def edit_draft(user, version_id, data):
    uid, v = get_version(user, version_id, lock=True)
    require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] != 'DRAFT':
        raise ValidationError('Nur Entwürfe können bearbeitet werden.')
    from .policies import default_due
    review_due = data.get('next_review_on') or default_due(v['document_type'],data.get('effective_from'))
    query('''UPDATE document_versions SET title=%s,change_summary=%s,effective_from=%s,next_review_on=%s,classification=%s
        WHERE id=%s''',[data['title'],data['change_summary'],data['effective_from'],review_due,data.get('classification',v['classification']),version_id])
    if not query('SELECT can_read_version(%s,%s) AS permitted',[uid,version_id])[0]['permitted']:
        raise ValidationError('Vor einer vertraulichen Einstufung musst du im Dokumentzugriff ausdrücklich berechtigt sein.')
    save_mappings(version_id,v['responsible_department_id'],data)
    audit(uid,'EDIT',version_id,data['change_summary'])


@transaction.atomic
def new_revision(user, version_id, kind='major', reason='Neue Überarbeitung'):
    uid, v = get_version(user, version_id, lock=True)
    require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] not in ('APPROVED','ARCHIVED'):
        raise ValidationError('Eine neue Revision setzt eine bereits freigegebene Ausgangsversion voraus.')
    if kind not in ('major','minor') or not reason.strip():
        raise ValidationError('Versionsart und Änderungsgrund sind erforderlich.')
    # Serialize numbering for all versions of the same document.
    query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if query("SELECT 1 FROM document_versions WHERE document_id=%s AND status IN ('DRAFT','IN_REVIEW','PENDING_APPROVAL')",[v['document_id']]):
        raise ValidationError('Es gibt bereits eine laufende Überarbeitung.')
    latest = query("SELECT id FROM document_versions WHERE document_id=%s AND status IN ('APPROVED','ARCHIVED') ORDER BY major DESC,minor DESC LIMIT 1",[v['document_id']])[0]['id']
    if latest != version_id:
        raise ValidationError('Die Überarbeitung muss von der neuesten freigegebenen Version ausgehen.')
    if kind=='major':
        major = query('SELECT max(major)+1 AS major FROM document_versions WHERE document_id=%s',[v['document_id']])[0]['major']
        minor = 0
    else:
        major = v['major']
        minor = query('SELECT max(minor)+1 AS minor FROM document_versions WHERE document_id=%s AND major=%s',[v['document_id'],major])[0]['minor']
    vid = query('''INSERT INTO document_versions(document_id,major,minor,title,change_summary,created_by,classification,next_review_on,effective_from)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',[v['document_id'],major,minor,v['title'],reason,uid,v['classification'],v['next_review_on'],timezone.now()])[0]['id']
    for table, column in [('version_departments','department_id'),('version_standard_links','reference_id')]:
        # Table/column names come exclusively from these constants.
        query(f'INSERT INTO {table}(version_id,{column}) SELECT %s,{column} FROM {table} WHERE version_id=%s',[vid,version_id])
    query('INSERT INTO version_files(version_id,file_id,purpose) SELECT %s,file_id,purpose FROM version_files WHERE version_id=%s',[vid,version_id])
    query('UPDATE document_versions SET approval_based_validity=true WHERE id=%s',[vid])
    query('INSERT INTO version_distribution(version_id,change_kind,requires_ack,ack_days,keywords) SELECT %s,change_kind,requires_ack,ack_days,keywords FROM version_distribution WHERE version_id=%s',[vid,version_id])
    query('INSERT INTO version_audiences(version_id,audience_id) SELECT %s,audience_id FROM version_audiences WHERE version_id=%s',[vid,version_id])
    audit(uid,'CREATE_REVISION',vid,reason,{'source_version':version_id,'kind':kind,'version':f'{major}.{minor}'})
    return vid


@transaction.atomic
def remove_file(user, version_id, file_id, reason):
    uid,v = get_version(user,version_id,lock=True)
    require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] != 'DRAFT' or not reason.strip():
        raise ValidationError('Dateien können nur im Entwurf und mit Begründung entfernt werden.')
    if not query('SELECT 1 FROM version_files WHERE version_id=%s AND file_id=%s',[version_id,file_id]):
        raise ValidationError('Datei gehört nicht zu diesem Entwurf.')
    query('DELETE FROM version_files WHERE version_id=%s AND file_id=%s',[version_id,file_id])
    audit(uid,'UNLINK_FILE',version_id,reason,{'file_id':file_id})


def save_mappings(version_id, department, data):
    # Called only inside a locked draft transaction by create_document/edit_draft.
    for key,table,column in [('applicable_departments','version_departments','department_id'),('standard_references','version_standard_links','reference_id')]:
        if key not in data:
            continue
        values = set(data[key])
        if key=='applicable_departments':
            values.add(department)
        query(f'DELETE FROM {table} WHERE version_id=%s',[version_id])
        for value in sorted(values):
            query(f'INSERT INTO {table}(version_id,{column}) VALUES (%s,%s)',[version_id,value])


@transaction.atomic
def record_review(user, version_id, result, rationale, next_review_on=None):
    uid,v = get_version(user,version_id,lock=True)
    from .policies import require_qmb
    require_qmb(user)
    if uid == v['created_by']:
        raise PermissionDenied('Die periodische Prüfung muss unabhängig vom Ersteller erfolgen.')
    if v['status']!='APPROVED' or query('SELECT current_release(%s) AS id',[v['document_id']])[0]['id'] != version_id:
        raise ValidationError('Nur die aktuell wirksame freigegebene Fassung kann geprüft werden.')
    if result not in ('UNCHANGED','REVISION_REQUIRED','WITHDRAWAL_REQUIRED') or not rationale.strip():
        raise ValidationError('Prüfergebnis und Begründung sind erforderlich.')
    from .policies import interval_for,add_months
    months = interval_for(v['document_type'])
    if result=='UNCHANGED' and next_review_on is None:
        next_review_on = add_months(timezone.localdate(),months)
    if result=='UNCHANGED' and next_review_on>add_months(timezone.localdate(),months):
        raise ValidationError('Der Prüftermin darf die Gültigkeit der Kategorie nicht überschreiten.')
    if next_review_on and next_review_on<=timezone.localdate():
        raise ValidationError('Der neue Prüftermin muss in der Zukunft liegen.')
    review = query('INSERT INTO periodic_reviews(version_id,reviewer_id,result,rationale,next_review_on,review_interval_months) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',[version_id,uid,result,rationale,next_review_on,months])[0]['id']
    audit(uid,'PERIODIC_REVIEW',version_id,rationale,{'review_id':review,'result':result,'review_interval_months':months,'next_review_on':str(next_review_on) if next_review_on else None})
    return review



def version_history(user, version_id):
    uid,v = get_version(user,version_id)
    if not any(allowed(uid,v['responsible_department_id'],r,v['document_id']) for r in ('AUTHOR','REVIEWER')):
        raise PermissionDenied('Die Versionshistorie ist auf Dokumentenverantwortliche und Prüfrollen beschränkt.')
    versions = query("""SELECT v.*,u.display_name AS author_name,
        (v.id=current_release(v.document_id)) AS current_release
        FROM document_versions v JOIN users u ON u.id=v.created_by
        WHERE v.document_id=%s AND can_read_version(%s,v.id) ORDER BY v.major DESC,v.minor DESC""",[v['document_id'],uid])
    decisions = query("""SELECT a.*,u.display_name AS actor_name,w.started_at,w.closed_at
        FROM approval_decisions a JOIN users u ON u.id=a.actor_id
        JOIN workflow_instances w ON w.id=a.workflow_id
        JOIN document_versions v ON v.id=a.version_id
        WHERE v.document_id=%s AND can_read_version(%s,v.id) ORDER BY a.id DESC""",[v['document_id'],uid])
    audit(uid,'VIEW_HISTORY',version_id,'Versions- und Freigabehistorie eingesehen')
    return v,versions,decisions


def access_policy(document_id):
    mode = query('SELECT access_mode FROM documents WHERE id=%s',[document_id])[0]['access_mode']
    people = query('SELECT user_id FROM document_access_users WHERE document_id=%s ORDER BY user_id',[document_id])
    groups = query('SELECT group_id FROM document_access_groups WHERE document_id=%s ORDER BY group_id',[document_id])
    return {'access_mode':mode,'users':people,'groups':groups}


@transaction.atomic
def change_access(user,version_id,access_mode,users,groups,reason):
    uid,v = get_version(user,version_id,lock=True)
    document_id = v['document_id']
    require(uid,v['responsible_department_id'],'AUTHOR',document_id)
    query('SELECT id FROM documents WHERE id=%s FOR UPDATE',[document_id])
    if access_mode not in ('DEPARTMENT','EXPLICIT') or not reason.strip():
        raise ValidationError('Zugriffsbereich und Begründung sind erforderlich.')
    before = access_policy(document_id)
    query('UPDATE documents SET access_mode=%s WHERE id=%s',[access_mode,document_id])
    for table,column,values in [('document_access_users','user_id',users),('document_access_groups','group_id',groups)]:
        query(f'DELETE FROM {table} WHERE document_id=%s',[document_id])
        for value in sorted(set(values)):
            query(f'INSERT INTO {table}(document_id,{column}) VALUES (%s,%s)',[document_id,value])
    if not query('SELECT can_read_version(%s,%s) AS permitted',[uid,version_id])[0]['permitted']:
        raise ValidationError('Du musst selbst weiterhin berechtigt bleiben. Änderungen wurden nicht gespeichert.')
    audit(uid,'CHANGE_ACCESS',version_id,reason,{'document_id':document_id,'before':before,'after':access_policy(document_id)})


@transaction.atomic
def lifecycle_action(user,version_id,action,reason,confirmed=False):
    uid,v = get_version(user,version_id,lock=True)
    from .policies import require_qmb
    require_qmb(user)
    if not confirmed or not reason.strip() or action not in ('withdraw','archive'):
        raise ValidationError('Gültiger Vorgang, Begründung und Bestätigung sind erforderlich.')
    query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if action=='archive':
        if v['status']!='APPROVED':
            raise ValidationError('Nur freigegebene Fassungen können archiviert werden.')
        query("UPDATE document_versions SET status='ARCHIVED' WHERE id=%s",[version_id])
        audit(uid,'ARCHIVE',version_id,reason,{'document_id':v['document_id']})
    else:
        released = query("SELECT 1 FROM document_versions WHERE document_id=%s AND status='APPROVED'",[v['document_id']])
        if not released:
            raise ValidationError('Das Dokument besitzt keine freigegebene Fassung.')
        latest = query('SELECT withdrawn_at FROM document_withdrawals WHERE document_id=%s ORDER BY id DESC LIMIT 1',[v['document_id']])
        if latest and not query("SELECT 1 FROM approval_decisions a JOIN document_versions dv ON dv.id=a.version_id WHERE dv.document_id=%s AND a.stage='APPROVAL' AND a.decision='ACCEPT' AND a.decided_at>%s",[v['document_id'],latest[0]['withdrawn_at']]):
            raise ValidationError('Das Dokument ist bereits zurückgezogen.')
        withdrawal = query('INSERT INTO document_withdrawals(document_id,actor_id,reason) VALUES (%s,%s,%s) RETURNING id',[v['document_id'],uid,reason])[0]['id']
        audit(uid,'WITHDRAW_DOCUMENT',version_id,reason,{'document_id':v['document_id'],'withdrawal_id':withdrawal})


def workflow_tasks(user):
    uid = actor(user)
    return query("""SELECT v.id,v.document_id,v.title,v.major,v.minor,v.status,d.number,w.started_at,
        CASE WHEN v.status='IN_REVIEW' THEN 'QMB-Prüfung' ELSE 'Freigabe nach QMB-Prüfung' END AS task_label
        FROM document_versions v JOIN documents d ON d.id=v.document_id
        JOIN workflow_instances w ON w.version_id=v.id AND w.closed_at IS NULL
        WHERE (is_qmb(%s) OR can_lead_approve(%s,v.id)) AND can_read_version(%s,v.id)
          AND v.created_by<>%s AND w.submitted_by<>%s
          AND v.status IN ('IN_REVIEW','PENDING_APPROVAL')
        ORDER BY w.started_at,v.id LIMIT 5000""",[uid,uid,uid,uid,uid])



@transaction.atomic
def takeover_review(user,version_id,reason):
    from .policies import require_qmb
    uid = require_qmb(user)
    _,v = get_version(user,version_id,lock=True)
    query('SELECT pg_advisory_xact_lock(%s)',[v['document_id']])
    if v['status']!='PENDING_APPROVAL' or not reason.strip() or uid==v['created_by']:
        raise ValidationError('Übernahme erfordert eine fremde, bereits geprüfte Fassung und eine Begründung.')
    w = query('SELECT * FROM workflow_instances WHERE version_id=%s AND closed_at IS NULL FOR UPDATE',[version_id])[0]
    if uid==w['submitted_by']:
        raise PermissionDenied('Der Einreicher kann die Prüfung nicht selbst übernehmen.')
    query('UPDATE workflow_instances SET closed_at=clock_timestamp() WHERE id=%s',[w['id']])
    query("UPDATE document_versions SET status='DRAFT' WHERE id=%s",[version_id])
    query('INSERT INTO workflow_instances(version_id,content_fingerprint,submitted_by) VALUES (%s,%s,%s)',[version_id,fingerprint(v),w['submitted_by']])
    query("UPDATE document_versions SET status='IN_REVIEW' WHERE id=%s",[version_id])
    audit(uid,'QMB_TAKEOVER',version_id,reason,{'previous_workflow_id':w['id']})
