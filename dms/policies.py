import calendar
from datetime import date
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from .services import actor,query


def add_months(day,months):
    year,month = divmod(day.year*12+day.month-1+months,12)
    month += 1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))


def interval_for(category):
    rows = query('SELECT review_interval_months FROM document_categories WHERE name=%s FOR SHARE',[category])
    if not rows:
        raise ValidationError('Dokumentkategorie ist nicht vorhanden.')
    return rows[0]['review_interval_months']


def default_due(category,effective_from=None):
    if effective_from is None:
        anchor = timezone.localdate()
    else:
        anchor = timezone.localtime(effective_from).date()
    try:
        return add_months(anchor,interval_for(category))
    except ValueError:
        raise ValidationError('Das Wirksamkeitsdatum liegt außerhalb des unterstützten Zeitraums.')


def is_settings_admin(user):
    if not user.is_authenticated or not user.is_active:
        return False
    return bool(query("SELECT 1 FROM users WHERE auth_user_id=%s AND active AND has_role(id,'ADMIN',NULL,NULL)",[user.pk]))


def require_settings_admin(user):
    if not is_settings_admin(user):
        raise PermissionDenied('Nur die IT-Administration darf Systemeinstellungen ändern.')
    return actor(user)


@transaction.atomic
def save_intervals(user,intervals,reason):
    uid = require_qmb(user)
    query("SELECT pg_advisory_xact_lock(hashtext('ims-master-data'))")
    if not reason.strip():
        raise ValidationError('Eine Begründung ist erforderlich.')
    categories = query('SELECT * FROM document_categories WHERE active ORDER BY id FOR UPDATE')
    if set(intervals)!={c['id'] for c in categories}:
        raise ValidationError('Kategorien haben sich geändert. Bitte die Einstellungen neu laden.')
    if any(not isinstance(value,int) or isinstance(value,bool) or not 1<=value<=1200 for value in intervals.values()):
        raise ValidationError('Die Gültigkeit muss zwischen 1 und 1200 Monaten liegen.')
    for category in categories:
        months = intervals[category['id']]
        if months==category['review_interval_months']:
            continue
        query('UPDATE document_categories SET review_interval_months=%s,updated_at=clock_timestamp() WHERE id=%s',[months,category['id']])
        import json
        query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_REVIEW_POLICY','category',%s,%s,%s::jsonb)",[uid,str(category['id']),reason,json.dumps({'category':category.get('display_name') or category['name'],'before_months':category['review_interval_months'],'after_months':months})])



def is_qmb(user):
    if not user.is_authenticated or not user.is_active:
        return False
    return bool(query('SELECT 1 FROM users WHERE auth_user_id=%s AND is_qmb(id)',[user.pk]))


def require_qmb(user):
    if not is_qmb(user):
        raise PermissionDenied('Diese Funktion ist benannten QMB-Konten vorbehalten.')
    return actor(user)


@transaction.atomic
def save_qmb_team(user,primary_id,deputy_id,reason,lead_id=None):
    uid = require_settings_admin(user)
    if not reason.strip() or (primary_id and primary_id==deputy_id):
        raise ValidationError('QMB und Vertretung müssen unterschiedliche Personen sein; Begründung erforderlich.')
    query("SELECT pg_advisory_xact_lock(hashtext('ims-qmb-team'))")
    before = query("SELECT id,qmb_role,qmb_approval_lead FROM users WHERE qmb_role<>'NONE' OR qmb_approval_lead ORDER BY id FOR UPDATE")
    selected = list({value for value in (primary_id,deputy_id,lead_id) if value})
    if selected and len(query('SELECT u.id FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=ANY(%s::bigint[]) AND u.active AND a.is_active', [selected]))!=len(selected):
        raise ValidationError('Nur aktive Benutzer können als QMB benannt werden.')
    query("UPDATE users SET qmb_role='NONE' WHERE qmb_role<>'NONE'")
    query('UPDATE users SET qmb_approval_lead=false WHERE qmb_approval_lead')
    if lead_id:
        query('UPDATE users SET qmb_approval_lead=true WHERE id=%s',[lead_id])
    for person,role in [(primary_id,'PRIMARY'),(deputy_id,'DEPUTY')]:
        if person:
            query('UPDATE users SET qmb_role=%s WHERE id=%s',[role,person])
    import json
    query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_QMB_TEAM','settings','qmb',%s,%s::jsonb)",[uid,reason,json.dumps({'before':before,'primary_id':primary_id,'deputy_id':deputy_id,'lead_id':lead_id})])


@transaction.atomic
def save_category_management(user,intervals,retention,locations,reason):
    require_qmb(user)
    query("SELECT pg_advisory_xact_lock(hashtext('ims-master-data'))")
    save_intervals(user,intervals,reason)
    for category_id in intervals:
        before = query('SELECT retention_months,storage_location_id FROM document_categories WHERE id=%s',[category_id])[0]
        months = retention[category_id]
        location = locations[category_id]
        if months is not None and not 1<=months<=1200:
            raise ValidationError('Ungültige Aufbewahrungsfrist.')
        if not query('SELECT 1 FROM storage_locations WHERE id=%s AND active',[location]):
            raise ValidationError('Aktiven Aufbewahrungsort auswählen.')
        after = {'retention_months':months,'storage_location_id':location}
        if before!=after:
            query('UPDATE document_categories SET retention_months=%s,storage_location_id=%s,updated_at=clock_timestamp() WHERE id=%s',[months,location,category_id])
            import json
            query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_RETENTION_POLICY','category',%s,%s,%s::jsonb)",[actor(user),str(category_id),reason,json.dumps({'before':before,'after':after})])
