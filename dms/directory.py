"""Prepared directory configuration; authentication remains local until integrated."""
from .audit_text import optional_reason
import base64
import hashlib
import ipaddress
import json
import re
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from . import services as s
from .policies import require_settings_admin

FIELDS = ('directory_type','host','port','security','domain','base_dn','bind_identity','user_base_dn',
    'user_filter','username_attribute','name_attribute','email_attribute','identity_attribute',
    'group_base_dn','group_filter','membership_attribute','timeout_seconds')


def cipher():
    key = getattr(settings,'LDAP_ENCRYPTION_KEY','') or base64.urlsafe_b64encode(
        hashlib.sha256(b'ims-dms:ldap:v1:'+settings.SECRET_KEY.encode()).digest())
    try:
        return Fernet(key)
    except (ValueError,TypeError):
        raise ValidationError('LDAP-Verschlüsselungsschlüssel ist ungültig. IT-Betriebskonfiguration prüfen.')


def load_config():
    return s.query('SELECT * FROM directory_settings WHERE id=1')[0]


def public_config(config):
    return {field:config[field] for field in FIELDS} | {'password_set':bool(config['password_ciphertext']), 'updated_at':config['updated_at']}


def validate_config(config):
    if config['directory_type'] not in ('AD','LDAP') or config['security'] not in ('LDAPS','STARTTLS'):
        raise ValidationError('Ungültiger Verzeichnistyp oder Transport.')
    if not 1<=config['port']<=65535 or not 1<=config['timeout_seconds']<=60:
        raise ValidationError('Port oder Zeitlimit ungültig.')
    host = config['host']
    if host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',host):
                raise ValidationError('Server als Hostname oder IP ohne Protokoll, Pfad oder Zugangsdaten angeben.')
    for field in FIELDS:
        value = config[field]
        if isinstance(value,str) and (len(value)>2000 or any(ord(c)<32 for c in value)):
            raise ValidationError('Ungültige Zeichen oder zu langer Konfigurationswert.')
    for field in ('username_attribute','name_attribute','email_attribute','identity_attribute','membership_attribute'):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*(?:;binary)?',config[field]):
            raise ValidationError('Ungültiger LDAP-Attributname.')
    if config['user_filter'].count('{username}')!=1 or not config['user_filter'].startswith('(') or not config['user_filter'].endswith(')'):
        raise ValidationError('Der Benutzerfilter muss in Klammern stehen und genau einmal {username} enthalten.')
    remainder = config['user_filter'].replace('{username}','')
    if '{' in remainder or '}' in remainder:
        raise ValidationError('Im Benutzerfilter ist nur der Platzhalter {username} erlaubt.')
    if not config['group_filter'].startswith('(') or not config['group_filter'].endswith(')'):
        raise ValidationError('Der Gruppenfilter muss in Klammern stehen.')


@transaction.atomic
def save_config(user,data):
    data = dict(data,reason=optional_reason(data.get('reason')))
    uid = require_settings_admin(user)
    if data.get('clear_password') and data.get('password'):
        raise ValidationError('Kennwort entweder ersetzen oder entfernen.')
    before = s.query('SELECT * FROM directory_settings WHERE id=1 FOR UPDATE')[0]
    updated = dict(before)
    updated.update({field:data[field] for field in FIELDS})
    validate_config(updated)
    if data.get('password'):
        updated['password_ciphertext'] = cipher().encrypt(data['password'].encode()).decode()
    elif data.get('clear_password'):
        updated['password_ciphertext'] = ''
    assignments = ','.join(field+'=%s' for field in FIELDS)
    s.query(f'UPDATE directory_settings SET {assignments},password_ciphertext=%s,updated_at=clock_timestamp() WHERE id=1',
        [*[updated[field] for field in FIELDS],updated['password_ciphertext']])
    details = {'before':public_config(before),'after':public_config(updated),
        'password_changed':before['password_ciphertext']!=updated['password_ciphertext'],'authentication':'LOCAL'}
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_DIRECTORY_SETTINGS','settings','directory',%s,%s::jsonb)",
        [uid,data['reason'],json.dumps(details,default=str)])
