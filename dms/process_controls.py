"""Internal process risk register and KPI history. All entry points require QMB."""
import json
from datetime import date
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from . import services as s
from .policies import require_qmb, add_months


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def controls(user, process):
    require_qmb(user)
    rows = s.query("SELECT c.*,u.display_name,m.id AS latest_id,m.measured_on AS latest_on,m.value AS latest_value,m.definition AS latest_definition FROM process_controls c LEFT JOIN users u ON u.id=(c.payload->>'owner_id')::bigint LEFT JOIN LATERAL (SELECT id,measured_on,value,definition FROM process_measurements WHERE control_id=c.id ORDER BY measured_on DESC,id DESC LIMIT 1) m ON c.kind='kpi' WHERE c.process_id=%s ORDER BY c.active DESC,lower(c.payload->>'title'),c.id", [process])
    today = date.today()
    for item in rows:
        item['data'] = decode(item['payload'])
        data = item['data']
        if item['kind'] == 'risk':
            item['score'] = data['probability'] * data['impact']
            item['band'] = 'Hoch' if item['score'] >= 15 else 'Mittel' if item['score'] >= 6 else 'Niedrig'
            item['residual_score'] = data['residual_probability'] * data['residual_impact'] if data.get('residual_probability') and data.get('residual_impact') else None
            item['due_on'] = date.fromisoformat(data['due_on']) if data.get('due_on') else None
            item['overdue'] = bool(data.get('due_on') and date.fromisoformat(data['due_on']) < today and data['status'] in ('open','progress'))
        else:
            latest = [{'measured_on':item['latest_on'],'value':item['latest_value'],'definition':item['latest_definition']}] if item['latest_id'] else []
            item['latest'] = latest[0] if latest else None
            item['due_on'] = add_months(latest[0]['measured_on'], data['interval_months']) if latest else date.fromisoformat(data['first_due'])
            item['overdue'] = item['due_on'] < today
            if latest:
                definition = decode(latest[0]['definition'])
                item['met'] = latest[0]['value'] >= Decimal(definition['target']) if definition['direction'] == 'gte' else latest[0]['value'] <= Decimal(definition['target'])
                item['measured_unit'] = definition['unit']
                item['definition_changed'] = definition != data
    return rows


@transaction.atomic
def save(user, process, target, kind, data, active, expected, reason):
    actor = require_qmb(user)
    try:
        with transaction.atomic():
            return s.query('SELECT save_process_control(%s,%s,%s,%s,%s::jsonb,%s,%s,%s) AS id', [actor,process,target,kind,json.dumps(data),active,expected,reason])[0]['id']
    except DatabaseError as error:
        if getattr(error.__cause__, 'sqlstate', None) in ('P0001','P0002','23503','23514'):
            raise ValidationError('Speichern nicht möglich. Angaben und aktiven Verantwortlichen prüfen. Bei parallelen Änderungen die Seite neu laden.') from error
        raise


@transaction.atomic
def measure(user, target, day, value, note, expected):
    actor = require_qmb(user)
    try:
        with transaction.atomic():
            return s.query('SELECT record_process_measurement(%s,%s,%s,%s,%s,%s) AS id', [actor,target,day,value,note,expected])[0]['id']
    except DatabaseError as error:
        if getattr(error.__cause__, 'sqlstate', None) in ('P0001','P0002'):
            raise ValidationError('Messwert nicht gespeichert. Definition und Prozess müssen aktiv und unverändert sein. Datum darf nicht in der Zukunft liegen.') from error
        raise
