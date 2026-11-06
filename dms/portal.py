"""Employee distribution supplements access control; audiences never grant access."""
from .audit_text import optional_reason
from datetime import timedelta
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from . import services as s
from .policies import require_qmb,require_settings_admin,add_months


def relevant_ids(uid):
    return {r['id'] for r in s.query('''SELECT v.id FROM document_versions v
        WHERE (NOT EXISTS(SELECT 1 FROM version_audiences va WHERE va.version_id=v.id)
          AND (NOT EXISTS(SELECT 1 FROM user_workplaces p WHERE p.user_id=%s AND p.department_id IS NOT NULL)
               OR EXISTS(SELECT 1 FROM version_departments vd JOIN user_workplaces p ON p.department_id=vd.department_id WHERE vd.version_id=v.id AND p.user_id=%s)))
        OR EXISTS(SELECT 1 FROM version_audiences va JOIN audience_memberships m ON m.audience_id=va.audience_id
          JOIN audience_groups g ON g.id=m.audience_id AND g.active WHERE va.version_id=v.id AND m.user_id=%s)''',[uid,uid,uid])}


def current_versions(user,search='',personal=False,department='',standard=''):
    uid = s.actor(user)
    rows = s.visible_versions(user,search=search,department=department,standard=standard,current_only=True,limit=5000)
    relevant = relevant_ids(uid)
    bookmarks = {r['document_id'] for r in s.query('SELECT document_id FROM document_bookmarks WHERE user_id=%s',[uid])}
    for row in rows:
        row['relevant'] = row['id'] in relevant
        row['bookmarked'] = row['document_id'] in bookmarks
    return [r for r in rows if not personal or r['relevant']]


def current_version(user,document_id):
    uid = s.actor(user)
    rows = s.query('''SELECT v.id FROM document_versions v WHERE v.document_id=%s AND v.id=current_release(%s)
        AND v.status='APPROVED' AND can_read_version(%s,v.id)''',[document_id,document_id,uid])
    if not rows:
        raise PermissionDenied('Keine aktuelle freigegebene Lesefassung verfügbar.')
    return rows[0]['id']


@transaction.atomic
def bookmark(user,document_id):
    current_version(user,document_id)
    uid = s.actor(user)
    s.query('SELECT pg_advisory_xact_lock(%s)',[uid])
    existing = s.query('DELETE FROM document_bookmarks WHERE user_id=%s AND document_id=%s RETURNING document_id',[uid,document_id])
    if not existing:
        s.query('INSERT INTO document_bookmarks(user_id,document_id) VALUES (%s,%s)',[uid,document_id])


@transaction.atomic
def save_distribution(user,version_id,change_kind,requires_ack,ack_days,keywords,audiences,reason):
    reason = optional_reason(reason)
    uid,v = s.get_version(user,version_id,lock=True)
    s.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status']!='DRAFT':
        raise ValidationError('Zielgruppen und Kenntnisnahme nur im Entwurf mit Begründung ändern.')
    if change_kind not in ('EDITORIAL','SUBSTANTIAL') or not 1<=ack_days<=3650 or len(keywords)>2000:
        raise ValidationError('Ungültige Verteilungsvorgabe.')
    groups = list(set(audiences))
    if len(s.query('SELECT id FROM audience_groups WHERE id=ANY(%s::bigint[]) AND active',[groups]))!=len(groups):
        raise ValidationError('Nur aktive Zielgruppen auswählen.')
    before = s.query('SELECT * FROM version_distribution WHERE version_id=%s',[version_id])
    s.query('''INSERT INTO version_distribution(version_id,change_kind,requires_ack,ack_days,keywords) VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(version_id) DO UPDATE SET change_kind=EXCLUDED.change_kind,requires_ack=EXCLUDED.requires_ack,ack_days=EXCLUDED.ack_days,keywords=EXCLUDED.keywords''',[version_id,change_kind,requires_ack,ack_days,keywords])
    s.query('DELETE FROM version_audiences WHERE version_id=%s',[version_id])
    for group in groups:
        s.query('INSERT INTO version_audiences(version_id,audience_id) VALUES (%s,%s)',[version_id,group])
    s.audit(uid,'CHANGE_DISTRIBUTION',version_id,reason,{'before':before,'audiences':groups,'requires_ack':requires_ack,'change_kind':change_kind})


@transaction.atomic
def assign_acknowledgements(user):
    uid = s.actor(user)
    ids = relevant_ids(uid)
    rows = s.query('''SELECT v.id,c.ack_days FROM document_versions v JOIN version_distribution c ON c.version_id=v.id
        WHERE c.requires_ack AND v.id=current_release(v.document_id) AND v.status='APPROVED'
        AND can_read_version(%s,v.id)''',[uid])
    for row in rows:
        if row['id'] in ids:
            s.query('''INSERT INTO acknowledgement_assignments(version_id,user_id,due_on) VALUES (%s,%s,%s)
                ON CONFLICT(version_id,user_id) DO NOTHING''',[row['id'],uid,timezone.localdate()+timedelta(days=row['ack_days'])])


def pending_acknowledgements(user):
    assign_acknowledgements(user)
    uid = s.actor(user)
    return s.query('''SELECT a.*,v.document_id,d.number,v.title,v.major,v.minor,v.change_summary FROM acknowledgement_assignments a
        JOIN document_versions v ON v.id=a.version_id JOIN documents d ON d.id=v.document_id
        WHERE a.user_id=%s AND NOT EXISTS(SELECT 1 FROM acknowledgement_receipts r WHERE r.assignment_id=a.id)
        AND v.id=current_release(v.document_id) AND v.status='APPROVED'
        AND can_read_version(%s,v.id) ORDER BY a.due_on,a.id''',[uid,uid])


@transaction.atomic
def acknowledge(user,assignment_id,confirmed):
    uid = s.actor(user)
    rows = s.query('''SELECT a.version_id FROM acknowledgement_assignments a JOIN document_versions v ON v.id=a.version_id
        WHERE a.id=%s AND a.user_id=%s AND v.id=current_release(v.document_id)
        AND can_read_version(%s,v.id) FOR UPDATE OF v''',[assignment_id,uid,uid])
    if not rows:
        raise PermissionDenied('Kenntnisnahme für diese Fassung nicht verfügbar.')
    if not confirmed:
        raise ValidationError('Bitte bestätigen, dass du die bezeichnete Fassung gelesen hast.')
    vid = rows[0]['version_id']
    _,v = s.get_version(user,vid)
    inserted = s.query('''INSERT INTO acknowledgement_receipts(assignment_id,content_fingerprint) VALUES (%s,%s)
        ON CONFLICT(assignment_id) DO NOTHING RETURNING id''',[assignment_id,s.fingerprint(v)])
    if inserted:
        s.audit(uid,'ACKNOWLEDGE',vid,'Kenntnisnahme der bezeichneten Fassung bestätigt',{'assignment_id':assignment_id})


@transaction.atomic
def create_audience(user,name,description,reason):
    reason = optional_reason(reason)
    uid = require_qmb(user)
    if not name.strip():
        raise ValidationError('Name und Begründung sind erforderlich.')
    group = s.query('INSERT INTO audience_groups(name,description) VALUES (%s,%s) RETURNING id',[name.strip(),description])[0]['id']
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason) VALUES (%s,'CREATE_AUDIENCE','audience',%s,%s)",[uid,str(group),reason])


@transaction.atomic
def save_workplace(user,user_id,department,site,activity,audiences,reason):
    reason = optional_reason(reason)
    uid = require_settings_admin(user)
    if not s.query('SELECT id FROM users WHERE id=%s',[user_id]):
        raise ValidationError('Gültiger Benutzer und Begründung erforderlich.')
    if department and not s.query('SELECT id FROM departments WHERE id=%s',[department]):
        raise ValidationError('Abteilung nicht vorhanden.')
    groups = list(set(audiences))
    if len(s.query('SELECT id FROM audience_groups WHERE active AND id=ANY(%s::bigint[])',[groups]))!=len(groups):
        raise ValidationError('Ungültige Zielgruppe.')
    before = s.query('SELECT * FROM user_workplaces WHERE user_id=%s',[user_id])
    before_groups = s.query('SELECT audience_id FROM audience_memberships WHERE user_id=%s',[user_id])
    s.query('''INSERT INTO user_workplaces(user_id,department_id,site,activity) VALUES (%s,%s,%s,%s)
        ON CONFLICT(user_id) DO UPDATE SET department_id=EXCLUDED.department_id,site=EXCLUDED.site,activity=EXCLUDED.activity''',[user_id,department,site,activity])
    s.query('DELETE FROM audience_memberships WHERE user_id=%s',[user_id])
    for group in groups:
        s.query('INSERT INTO audience_memberships(user_id,audience_id) VALUES (%s,%s)',[user_id,group])
    import json
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_WORKPLACE','user',%s,%s,%s::jsonb)",[uid,str(user_id),reason,json.dumps({'before':before,'before_audiences':before_groups,'department':department,'site':site,'activity':activity,'audiences':groups},default=str)])

@transaction.atomic
def synchronize_acknowledgements():
    """Assign to all eligible employees, including those who have never logged in."""
    return len(s.query('''INSERT INTO acknowledgement_assignments(version_id,user_id,due_on)
        SELECT v.id,u.id,(CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Berlin')::date+c.ack_days
        FROM version_distribution c JOIN document_versions v ON v.id=c.version_id
        CROSS JOIN users u JOIN auth_user auth ON auth.id=u.auth_user_id AND auth.is_active
        WHERE u.active AND c.requires_ack AND v.status='APPROVED' AND v.id=current_release(v.document_id)
       
        AND NOT EXISTS(SELECT 1 FROM acknowledgement_assignments a WHERE a.version_id=v.id AND a.user_id=u.id)
        AND ((NOT EXISTS(SELECT 1 FROM version_audiences va WHERE va.version_id=v.id)
            AND (NOT EXISTS(SELECT 1 FROM user_workplaces p WHERE p.user_id=u.id AND p.department_id IS NOT NULL)
                OR EXISTS(SELECT 1 FROM user_workplaces p JOIN version_departments vd ON vd.department_id=p.department_id WHERE p.user_id=u.id AND vd.version_id=v.id)))
            OR EXISTS(SELECT 1 FROM version_audiences va JOIN audience_memberships m ON m.audience_id=va.audience_id JOIN audience_groups g ON g.id=m.audience_id AND g.active WHERE va.version_id=v.id AND m.user_id=u.id))
        AND can_read_version(u.id,v.id)
        ON CONFLICT(version_id,user_id) DO NOTHING RETURNING id'''))
