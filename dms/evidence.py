"""Immutable evidence content and append-only retention decisions."""
from .audit_text import optional_reason
import hashlib
from pathlib import Path
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from . import services as s,storage
from .policies import require_qmb,add_months


def records(user,search=''):
    uid = s.actor(user)
    return s.query('''SELECT r.*,coalesce(c.display_name,c.name) AS category,d.name AS department,u.display_name AS owner,
        COALESCE(last.retain_until,r.retain_until) AS retention_due,COALESCE(last.legal_hold,false) AS legal_hold,
        EXISTS(SELECT 1 FROM evidence_disposal_requests x WHERE x.record_id=r.id) AS disposal_requested
        FROM evidence_records r JOIN document_categories c ON c.id=r.category_id
        JOIN departments d ON d.id=r.department_id JOIN users u ON u.id=r.owner_id
        LEFT JOIN LATERAL (SELECT retain_until,legal_hold FROM evidence_retention_events e WHERE e.record_id=r.id ORDER BY e.id DESC LIMIT 1) last ON true
        WHERE can_read_evidence(%s,r.id) AND (%s='' OR r.number ILIKE %s OR r.title ILIKE %s)
        ORDER BY r.occurred_on DESC,r.id DESC LIMIT 1000''',[uid,search,'%'+search+'%','%'+search+'%'])


def get_record(user,record_id,lock=False):
    uid = s.actor(user)
    rows = s.query('''SELECT r.*,f.original_name,COALESCE(last.retain_until,r.retain_until) AS retention_due,
        COALESCE(last.legal_hold,false) AS legal_hold,coalesce(c.display_name,c.name) AS category,d.name AS department,u.display_name AS owner_name
        FROM evidence_records r JOIN file_objects f ON f.id=r.file_id
        JOIN document_categories c ON c.id=r.category_id JOIN departments d ON d.id=r.department_id JOIN users u ON u.id=r.owner_id
        LEFT JOIN LATERAL (SELECT retain_until,legal_hold FROM evidence_retention_events WHERE record_id=r.id ORDER BY id DESC LIMIT 1) last ON true
        WHERE r.id=%s AND can_read_evidence(%s,r.id)'''+(' FOR UPDATE OF r' if lock else ''),[record_id,uid])
    if not rows:
        raise PermissionDenied('Nachweis nicht verfügbar.')
    return uid,rows[0]


@transaction.atomic
def create_record(user,data,uploaded):
    data = dict(data,reason=optional_reason(data.get('reason')))
    uid = s.actor(user)
    s.require(uid,data['department_id'],'AUTHOR')
    if not s.query('SELECT 1 FROM departments WHERE id=%s AND active',[data['department_id']]):
        raise ValidationError('Für neue Nachweise eine aktive Abteilung auswählen.')
    category = s.query('SELECT retention_months FROM document_categories WHERE id=%s AND active',[data['category_id']])
    if not category:
        raise ValidationError('Kategorie nicht vorhanden.')
    due = data.get('retain_until')
    if due is None:
        if not category[0]['retention_months']:
            raise ValidationError('Aufbewahrungsfrist für diese Kategorie oder ein konkretes Aufbewahrungsdatum festlegen.')
        due = add_months(data['occurred_on'],category[0]['retention_months'])
    if due<data['occurred_on']:
        raise ValidationError('Ungültiges Aufbewahrungsdatum.')
    if data.get('source_version_id'):
        s.get_version(user,data['source_version_id'])
    if not uploaded:
        raise ValidationError('Eine Nachweisdatei ist erforderlich.')
    name = Path(uploaded.name).name
    suffix = Path(name).suffix.lower()
    if suffix not in storage.ALLOWED:
        raise ValidationError('Erlaubt sind PDF, DOCX, XLSX, ODT und TXT.')
    settings.MEDIA_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    key = uuid.uuid4().hex
    path = settings.MEDIA_ROOT/key
    try:
        digest = hashlib.sha256()
        size = 0
        with path.open('xb') as stream:
            path.chmod(0o600)
            for chunk in uploaded.chunks():
                size += len(chunk)
                if size>storage.MAX_BYTES:
                    raise ValidationError('Maximale Dateigröße: 25 MiB.')
                stream.write(chunk)
                digest.update(chunk)
        if not size:
            raise ValidationError('Leere Nachweise sind nicht zulässig.')
        fid = s.query('INSERT INTO file_objects(storage_key,original_name,media_type,size_bytes,sha256) VALUES (%s,%s,%s,%s,%s) RETURNING id',[key,name,storage.ALLOWED[suffix],size,digest.hexdigest()])[0]['id']
        rid = s.query('''INSERT INTO evidence_records(number,title,category_id,department_id,owner_id,source_version_id,
            occurred_on,retain_until,classification,file_id,reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            [data['number'],data['title'],data['category_id'],data['department_id'],uid,data.get('source_version_id'),data['occurred_on'],due,data['classification'],fid,data['reason']])[0]['id']
        import json
        s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CREATE_EVIDENCE','evidence',%s,%s,%s::jsonb)",[uid,str(rid),data['reason'],json.dumps({'sha256':digest.hexdigest(),'retain_until':str(due)})])
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return rid


@transaction.atomic
def change_retention(user,record_id,retain_until,legal_hold,reason):
    reason = optional_reason(reason)
    uid = require_qmb(user)
    _,record = get_record(user,record_id,lock=True)
    if retain_until<record['retention_due']:
        raise ValidationError('Aufbewahrung darf nur verlängert werden.')
    s.query('INSERT INTO evidence_retention_events(record_id,actor_id,retain_until,legal_hold,reason) VALUES (%s,%s,%s,%s,%s)',[record_id,uid,retain_until,legal_hold,reason])
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason) VALUES (%s,'CHANGE_EVIDENCE_RETENTION','evidence',%s,%s)",[uid,str(record_id),reason])


@transaction.atomic
def request_disposal(user,record_id,reason):
    reason = optional_reason(reason)
    uid = require_qmb(user)
    _,record = get_record(user,record_id,lock=True)
    if record['legal_hold'] or record['retention_due']>=timezone.localdate():
        raise ValidationError('Aussonderung erst nach Ablauf der Frist und ohne Sperre vormerken.')
    if not s.query('SELECT id FROM evidence_disposal_requests WHERE record_id=%s',[record_id]):
        s.query('INSERT INTO evidence_disposal_requests(record_id,actor_id,reason) VALUES (%s,%s,%s)',[record_id,uid,reason])
        s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason) VALUES (%s,'REQUEST_EVIDENCE_DISPOSAL','evidence',%s,%s)",[uid,str(record_id),reason])


def download_record(user,record_id):
    uid,record = get_record(user,record_id)
    f = s.query('SELECT * FROM file_objects WHERE id=%s',[record['file_id']])[0]
    if len(f['storage_key'])!=32 or any(c not in '0123456789abcdef' for c in f['storage_key']):
        raise ValidationError('Ungültiger Speicherschlüssel.')
    try:
        content = (settings.MEDIA_ROOT/f['storage_key']).read_bytes()
    except OSError:
        raise ValidationError('Datei im Speicher nicht verfügbar.')
    if len(content)!=f['size_bytes'] or hashlib.sha256(content).hexdigest()!=f['sha256']:
        raise ValidationError('Integritätsprüfung des Nachweises fehlgeschlagen.')
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason) VALUES (%s,'DOWNLOAD_EVIDENCE','evidence',%s,'Nachweisdatei abgerufen')",[uid,str(record_id)])
    return f,content
