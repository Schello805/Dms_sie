"""Audited local account operations; no direct runtime auth-table writes."""
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password,check_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from . import services as s
from .policies import require_settings_admin


def revoke_sessions(auth_id):
    for session in Session.objects.all().iterator(chunk_size=200):
        if session.get_decoded().get('_auth_user_id') == str(auth_id):
            session.delete()


@transaction.atomic
def create_account(user, username, display_name, email, password1, password2, reason):
    uid = require_settings_admin(user)
    if password1 != password2:
        raise ValidationError('Die Passwörter stimmen nicht überein.')
    candidate = get_user_model()(username=username, email=email)
    validate_password(password1, candidate)
    if get_user_model().objects.filter(username=username).exists():
        raise ValidationError('Dieser Benutzername ist bereits vergeben.')
    return s.query('SELECT create_local_account(%s,%s,%s,%s,%s,%s) AS id',
        [uid,username,make_password(password1),display_name,email,reason])[0]['id']


@transaction.atomic
def set_active(user, user_id, enabled, reason):
    uid = require_settings_admin(user)
    if uid == user_id:
        raise ValidationError('Das eigene Konto kann hier nicht deaktiviert werden.')
    s.query("SELECT pg_advisory_xact_lock(hashtext('ims-user-roles'))")
    rows = s.query('SELECT auth_user_id,is_qmb(id) AS qmb FROM users WHERE id=%s FOR UPDATE',[user_id])
    if not rows:
        raise ValidationError('Benutzer prüfen.')
    if not enabled and rows[0]['qmb'] and not s.query('SELECT 1 FROM users WHERE id<>%s AND is_qmb(id)',[user_id]):
        raise ValidationError('Vorher einen weiteren aktiven QMB zuordnen.')
    s.query('SELECT set_account_active(%s,%s,%s,%s)',[uid,user_id,enabled,reason])
    revoke_sessions(rows[0]['auth_user_id'])


@transaction.atomic
def change_password(user, user_id, password1, password2, reason, old_password=None):
    uid = s.actor(user)
    if uid != user_id:
        require_settings_admin(user)
    elif old_password is None or not check_password(old_password,user.password):
        raise ValidationError('Das aktuelle Passwort ist nicht korrekt.')
    rows = s.query('SELECT auth_user_id FROM users WHERE id=%s',[user_id])
    if not rows:
        raise ValidationError('Benutzer prüfen.')
    if s.query('SELECT 1 FROM external_identities WHERE user_id=%s',[user_id]):
        raise ValidationError('Das Passwort dieses Verzeichniskontos wird extern verwaltet.')
    target = get_user_model().objects.get(pk=rows[0]['auth_user_id'])
    if password1 != password2:
        raise ValidationError('Die Passwörter stimmen nicht überein.')
    validate_password(password1,target)
    s.query('SELECT set_local_password(%s,%s,%s,%s)',[uid,user_id,make_password(password1),reason])
    revoke_sessions(target.pk)
