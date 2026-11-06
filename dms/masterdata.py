"""Audited master-data lifecycle. Stable IDs and category keys never change."""
from .audit_text import optional_reason
import json
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from . import services as s
from .policies import require_qmb,require_settings_admin

KINDS={
    'categories':('Kategorien','document_categories'),
    'departments':('Abteilungen','departments'),
    'locations':('Aufbewahrungsorte','storage_locations'),
    'standards':('Normausgaben','standards'),
    'references':('Normreferenzen','standard_references'),
    'groups':('Gruppen und Mitglieder','dms_groups'),
}


def require(user,kind):
    if kind not in KINDS:
        raise ValidationError('Unbekannter Stammdatenbereich.')
    return require_settings_admin(user) if kind=='groups' else require_qmb(user)


def get(kind,target):
    table=KINDS[kind][1]
    rows=s.query(f'SELECT * FROM {table} WHERE id=%s',[target])
    if not rows:
        raise ValidationError('Datensatz nicht gefunden.')
    row=rows[0]
    if kind=='categories':row['name']=row['display_name'] or row['name']
    if kind=='groups':row['members']=[r['user_id'] for r in s.query('SELECT user_id FROM group_memberships WHERE group_id=%s ORDER BY user_id',[target])]
    return row


def definition_locked(kind,target):
    if kind=='standards':
        return bool(s.query('SELECT 1 FROM standard_references r JOIN standard_reference_usage u ON u.reference_id=r.id WHERE r.standard_id=%s LIMIT 1',[target]))
    if kind=='references':
        return bool(s.query('SELECT 1 FROM standard_reference_usage WHERE reference_id=%s',[target]))
    return False


def save(user,kind,target,data):
    actor=require(user,kind)
    data=dict(data);reason=optional_reason(data.pop('reason',''))
    fields={
        'categories':{'name','active','review_interval_months','retention_months','storage_location_id'},
        'departments':{'name','code','active','parent_id'},
        'locations':{'name','description','active'},
        'standards':{'name','edition','active'},
        'references':{'standard_id','reference','label','active'},
        'groups':{'name','members','active'},
    }
    data={key:value for key,value in data.items() if key in fields[kind]}
    try:
        with transaction.atomic():
            return s.query('SELECT save_ims_master(%s,%s,%s,%s::jsonb,%s) AS id',[actor,kind,target,json.dumps(data),reason])[0]['id']
    except IntegrityError:
        raise ValidationError('Bezeichnung oder Kennung ist bereits vorhanden, oder eine Zuordnung ist ungültig.')
    except DatabaseError as error:
        if getattr(error.__cause__,'sqlstate',None)=='P0001':
            message=getattr(getattr(error.__cause__,'diag',None),'message_primary','')
            explanations={
                'Reassign or deactivate active categories':'Diesem Ort sind aktive Kategorien zugeordnet. Diese zuerst umstellen oder deaktivieren.',
                'Department hierarchy cannot contain cycles':'Diese übergeordnete Abteilung würde einen Kreislauf erzeugen.',
                'Legacy administrative group':'Diese Altgruppe enthält administrative Sonderrechte. Mitglieder und Status über die administrative CLI prüfen.',
                'Used standard definitions':'Diese Normausgabe wird bereits geprüft oder verwendet. Bitte eine neue Ausgabe anlegen.',
                'Used references':'Diese Normreferenz wird bereits geprüft oder verwendet. Bitte einen neuen Eintrag anlegen.',
                'Active storage location':'Bitte einen aktiven Aufbewahrungsort auswählen.',
                'Active parent department':'Bitte eine aktive übergeordnete Abteilung auswählen.',
                'Active standard':'Bitte eine aktive Normausgabe auswählen.',
            }
            raise ValidationError(next((text for key,text in explanations.items() if key in message),'Änderung nicht zulässig. Status, Zuordnungen und Begründung prüfen.'))
        raise


def grant(user,group_id,role,department_id,document_number,reason):
    reason = optional_reason(reason)
    actor=require_settings_admin(user)
    if role not in ('READER','AUTHOR') or (department_id and document_number):
        raise ValidationError('Rolle und genau einen Geltungsbereich prüfen.')
    document=None
    if document_number:
        rows=s.query('SELECT id FROM documents WHERE number=%s',[document_number])
        if not rows:raise ValidationError('Die angegebene Dokumentnummer existiert nicht.')
        document=rows[0]['id']
    s.query('SELECT set_ims_group_grant(%s,%s,%s,%s,%s,false,%s)',[actor,group_id,role,department_id,document,reason])


def revoke(user,group_id,assignment_id,reason):
    reason = optional_reason(reason)
    actor=require_settings_admin(user)
    rows=s.query("SELECT * FROM role_assignments WHERE id=%s AND group_id=%s AND role IN ('READER','AUTHOR')",[assignment_id,group_id])
    if not rows:raise ValidationError('Berechtigung prüfen.')
    row=rows[0]
    s.query('SELECT set_ims_group_grant(%s,%s,%s,%s,%s,true,%s)',[actor,group_id,row['role'],row['department_id'],row['document_id'],reason])
