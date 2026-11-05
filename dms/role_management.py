from django.db import transaction
from django.core.exceptions import ValidationError,PermissionDenied
from . import services as s
from .policies import require_settings_admin

@transaction.atomic
def save_roles(user,user_id,author,qmb,admin,reason):
    uid = require_settings_admin(user)
    if not reason.strip():
        raise ValidationError('Eine Begründung ist erforderlich.')
    s.query("SELECT pg_advisory_xact_lock(hashtext('ims-user-roles'))")
    rows = s.query('SELECT u.* FROM users u JOIN auth_user a ON a.id=u.auth_user_id AND a.is_active WHERE u.id=%s FOR UPDATE OF u',[user_id])
    if not rows or not rows[0]['active']:
        raise ValidationError('Aktiven Benutzer auswählen.')
    if user_id==uid and not admin:
        raise ValidationError('Das eigene Adminrecht kann hier nicht entzogen werden.')
    before = rows[0]
    if s.query("SELECT 1 FROM role_assignments r JOIN group_memberships m ON m.group_id=r.group_id JOIN dms_groups g ON g.id=r.group_id AND g.active WHERE m.user_id=%s AND r.role IN ('AUTHOR','ADMIN')",[user_id]):
        raise ValidationError('Gruppenbasierte Rechte zuerst in der Gruppenverwaltung ändern.')
    s.query('SELECT set_operational_roles(%s,%s,%s,%s,%s,%s)',[uid,user_id,author,qmb,admin,reason])
