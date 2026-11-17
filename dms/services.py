"""Transaction boundary for every document mutation; all SQL uses bound parameters."""
from .audit_text import optional_reason
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
    reason = optional_reason(reason)
    query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,%s,'version',%s,%s,%s::jsonb)", [uid, action, str(version_id), reason, json.dumps(details or {})])







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

# Public compatibility facade: callers keep the same transaction boundaries.
from .catalog_service import visible_versions
from .document_service import get_version,create_document,edit_draft,new_revision,remove_file,save_mappings
from .workflow_service import transition,record_review,workflow_tasks,takeover_review
from .access_service import version_history,access_policy,change_access,lifecycle_action
