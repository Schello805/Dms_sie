"""Review reminders: durable outbox, current access checks, explicit SMTP settings."""
from .version import APP_NAME
import base64
import hashlib
import ipaddress
import json
import re
import smtplib
import socket
import ssl
import uuid
from datetime import datetime,time,timedelta
from urllib.parse import urlsplit
from cryptography.fernet import Fernet,InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend
from django.core.validators import validate_email,URLValidator
from django.db import transaction
from django.utils import timezone
from . import services as s
from .policies import require_settings_admin


def cipher():
    key = getattr(settings,'SMTP_ENCRYPTION_KEY','')
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(b'ims-dms:smtp:v1:'+settings.SECRET_KEY.encode()).digest())
    try:
        return Fernet(key)
    except ValueError:
        raise ValidationError('SMTP-Verschlüsselungsschlüssel ist ungültig. Betriebskonfiguration prüfen.')


def load_config(lock=False):
    if lock:
        s.query('SELECT pg_advisory_xact_lock(824010,1)')
    return s.query('SELECT * FROM notification_settings WHERE id=1')[0]


def public_config(config):
    return {key:value for key,value in config.items() if key not in ('password_ciphertext','updated_at','id')} | {'password_set':bool(config['password_ciphertext'])}


def validate_config(config,require_ready=False):
    if not 0<=config['reminder_days']<=3650 or not 1<=config['smtp_port']<=65535:
        raise ValidationError('Vorlauf oder SMTP-Port ungültig.')
    if config['smtp_security'] not in ('STARTTLS','SSL','NONE'):
        raise ValidationError('Ungültige SMTP-Verschlüsselung.')
    host = config['smtp_host']
    if host and not re.fullmatch(r'[A-Za-z0-9.:_-]+',host):
        raise ValidationError('SMTP-Server als Hostname oder IP ohne Protokoll und Port angeben.')
    if ':' in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise ValidationError('Ungültige IPv6-Adresse des SMTP-Servers.')
    if config['sender_email']:
        validate_email(config['sender_email'])
    if config['base_url']:
        URLValidator(schemes=['http','https'])(config['base_url'])
        url = urlsplit(config['base_url'])
        if url.username or url.password or url.query or url.fragment:
            raise ValidationError('DMS-Adresse ohne Zugangsdaten, Query oder Fragment angeben.')
    if config['enabled'] or require_ready:
        if not host or not config['sender_email'] or not config['base_url']:
            raise ValidationError('SMTP-Server, Absender und DMS-Adresse sind erforderlich.')
        if config['smtp_username'] and not config['password_ciphertext']:
            raise ValidationError('Für den SMTP-Benutzernamen fehlt das Passwort.')
        if config['password_ciphertext']:
            try:
                cipher().decrypt(config['password_ciphertext'].encode())
            except (InvalidToken,ValueError):
                raise ValidationError('SMTP-Passwort ist nicht entschlüsselbar. Bitte neu eingeben.')


@transaction.atomic
def save_config(user,data):
    uid = require_settings_admin(user)
    s.query('SELECT pg_advisory_xact_lock(824010,1)')
    before = s.query('SELECT * FROM notification_settings WHERE id=1 FOR UPDATE')[0]
    updated = dict(before)
    keys = ('smtp_host','smtp_port','smtp_security','smtp_username','sender_email','base_url')
    updated.update({key:data[key] for key in keys})
    if data.get('clear_password'):
        updated['password_ciphertext'] = ''
    if data.get('password'):
        updated['password_ciphertext'] = cipher().encrypt(data['password'].encode()).decode()
    if not data.get('reason','').strip():
        raise ValidationError('Eine Begründung ist erforderlich.')
    validate_config(updated)
    s.query('''UPDATE notification_settings SET enabled=%s,reminder_days=%s,smtp_host=%s,smtp_port=%s,
        smtp_security=%s,smtp_username=%s,sender_email=%s,base_url=%s,password_ciphertext=%s,updated_at=clock_timestamp() WHERE id=1''',
        [updated['enabled'],updated['reminder_days'],*[updated[key] for key in keys],updated['password_ciphertext']])
    details = {'before':public_config(before),'after':public_config(updated),'password_changed':before['password_ciphertext']!=updated['password_ciphertext']}
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_MAIL_SETTINGS','settings','1',%s,%s::jsonb)",[uid,data['reason'],json.dumps(details)])
    if updated['enabled']:
        retried = s.query("UPDATE review_notifications SET status='PENDING',error_code='',next_attempt_at=clock_timestamp() WHERE status='FAILED' AND error_code IN ('SMTP_REJECTED','CONFIGURATION') RETURNING id")
        for row in retried:
            mail_event('MAIL_RETRY',row['id'],'SMTP-Einstellungen aktualisiert',actor_id=uid)


def mail_event(action,job_id,reason,details=None,actor_id=None):
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,%s,'notification',%s,%s,%s::jsonb)",[actor_id,action,str(job_id),reason,json.dumps(details or {})])


def queue_due(today=None):
    today = today or timezone.localdate()
    config = load_config()
    if not config['enabled']:
        return 0
    candidates = s.query('''SELECT v.id AS version_id,rp.recipient_id,rp.recipient_kind,r.review_due_on AS due_on
        FROM document_versions v JOIN documents d ON d.id=v.document_id
        JOIN version_review_status r ON r.version_id=v.id
        CROSS JOIN LATERAL (SELECT d.owner_id AS recipient_id,'OWNER'::text AS recipient_kind UNION ALL
            SELECT u.id,'QMB' FROM users u WHERE is_qmb(u.id) AND u.id<>d.owner_id) rp
        WHERE v.id=current_release(d.id) AND v.status='APPROVED'
          AND r.review_due_on<=%s AND can_read_version(rp.recipient_id,v.id)''',[today+timedelta(days=config['reminder_days'])])
    count = 0
    for candidate in candidates:
        kind = 'DUE' if candidate['due_on']<=today else 'BEFORE'
        with transaction.atomic():
            rows = s.query('''INSERT INTO review_notifications AS n(version_id,recipient_id,due_on,kind,message_id,recipient_kind)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (version_id,recipient_id,due_on,kind) DO UPDATE SET status='PENDING',error_code='',next_attempt_at=clock_timestamp(),lease_token=NULL WHERE (n.status='CANCELLED' AND n.error_code='NO_ACCESS') OR (n.status='PENDING' AND n.next_attempt_at>clock_timestamp()) RETURNING id''',
                [candidate['version_id'],candidate['recipient_id'],candidate['due_on'],kind,f'<{uuid.uuid4().hex}@ims-dms.local>',candidate['recipient_kind']])
            if rows:
                mail_event('MAIL_QUEUED',rows[0]['id'],'Review-Erinnerung vorgemerkt',{'kind':kind,'due_on':str(candidate['due_on'])})
                count += 1
    return count


@transaction.atomic
def claim():
    expired = s.query("UPDATE review_notifications SET status='UNCERTAIN',error_code='INTERRUPTED_SEND',lease_token=NULL WHERE status='SENDING' AND claimed_at<clock_timestamp()-interval '5 minutes' RETURNING id")
    for row in expired:
        mail_event('MAIL_UNCERTAIN',row['id'],'Versand unterbrochen; vor erneutem Versand manuell prüfen')
    token = str(uuid.uuid4())
    rows = s.query('''WITH next AS (SELECT id FROM review_notifications WHERE status='PENDING'
        AND next_attempt_at<=clock_timestamp() ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
        UPDATE review_notifications n SET status='SENDING',attempts=attempts+1,lease_token=%s::uuid,claimed_at=clock_timestamp()
        FROM next WHERE n.id=next.id RETURNING n.*''',[token])
    return rows[0] if rows else None


def smtp_send(config,recipient,subject,body,message_id):
    validate_config(config,require_ready=True)
    password = cipher().decrypt(config['password_ciphertext'].encode()).decode() if config['password_ciphertext'] else ''
    connection = EmailBackend(host=config['smtp_host'],port=config['smtp_port'],username=config['smtp_username'],password=password,
        use_tls=config['smtp_security']=='STARTTLS',use_ssl=config['smtp_security']=='SSL',timeout=10,fail_silently=False)
    message = EmailMessage(subject,body,config['sender_email'],[recipient],connection=connection,headers={'Message-ID':message_id})
    with connection:
        if message.send(fail_silently=False)!=1:
            raise RuntimeError('SEND_NOT_CONFIRMED')


def finish(job,status,error='',email=''):
    rows = s.query('''UPDATE review_notifications SET status=%s,error_code=%s,recipient_email=%s,
        sent_at=CASE WHEN %s='SENT' THEN clock_timestamp() ELSE sent_at END,lease_token=NULL
        WHERE id=%s AND lease_token=%s::uuid AND status='SENDING' RETURNING id''',[status,error,email,status,job['id'],str(job['lease_token'])])
    if rows:
        mail_event('MAIL_'+status,job['id'],'Review-Erinnerung: '+status,{'error_code':error})


def failure_status(exc):
    if isinstance(exc,(smtplib.SMTPAuthenticationError,smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPDataError,smtplib.SMTPConnectError,smtplib.SMTPNotSupportedError,ConnectionRefusedError,socket.gaierror,ssl.SSLError,ValidationError)):
        return 'FAILED','SMTP_REJECTED' if not isinstance(exc,ValidationError) else 'CONFIGURATION'
    return 'UNCERTAIN','SMTP_RESULT_UNKNOWN'


def dispatch_one(today=None):
    today = today or timezone.localdate()
    if not load_config()['enabled']:
        return False
    job = claim()
    if not job:
        return False
    with transaction.atomic():
        version = s.query('SELECT id,document_id FROM document_versions WHERE id=%s FOR UPDATE',[job['version_id']])[0]
        s.query('SELECT pg_advisory_xact_lock(%s)',[version['document_id']])
        config = load_config(lock=True)
        if not config['enabled']:
            s.query("UPDATE review_notifications SET status='PENDING',lease_token=NULL WHERE id=%s",[job['id']])
            return True
        rows = s.query('''SELECT v.title,d.number,d.owner_id,u.email,a.email AS auth_email,u.active,a.is_active,is_qmb(u.id) AS recipient_is_qmb,
            r.review_due_on,can_read_version(u.id,v.id) AS readable,(v.id=current_release(d.id)) AS is_current,
            v.valid_until
            FROM document_versions v JOIN documents d ON d.id=v.document_id
            JOIN users u ON u.id=%s JOIN auth_user a ON a.id=u.auth_user_id
            JOIN version_review_status r ON r.version_id=v.id WHERE v.id=%s''',[job['recipient_id'],job['version_id']])
        row = rows[0] if rows else None
        if not row or (job['recipient_kind']=='OWNER' and row['owner_id']!=job['recipient_id']) or (job['recipient_kind']=='QMB' and not row['recipient_is_qmb']) or not row['is_current'] or row['review_due_on']!=job['due_on']:
            finish(job,'CANCELLED','NO_LONGER_CURRENT')
            return True
        if not row['active'] or not row['is_active'] or not row['readable']:
            finish(job,'CANCELLED','NO_ACCESS')
            return True
        if job['kind']=='BEFORE' and today>=job['due_on']:
            finish(job,'CANCELLED','EXPIRY_REMINDER_REPLACES_PREVIEW')
            return True
        eligible = job['due_on'] if job['kind']=='DUE' else job['due_on']-timedelta(days=config['reminder_days'])
        if today<eligible:
            next_time = timezone.make_aware(datetime.combine(eligible,time.min))
            s.query("UPDATE review_notifications SET status='PENDING',lease_token=NULL,next_attempt_at=%s WHERE id=%s",[next_time,job['id']])
            return True
        recipient = (row['email'] or row['auth_email'] or '').strip()
        try:
            validate_email(recipient)
        except ValidationError:
            finish(job,'FAILED','MISSING_EMAIL')
            return True
        subject_number = ' '.join(row['number'].split())[:100]
        when = 'heute fällig' if job['due_on']==today else ('überfällig' if job['due_on']<today else 'bald fällig')
        subject = f'DMS: Review {when} – {subject_number}'
        body = (f"Bitte das Dokument {row['number']} auf Richtigkeit prüfen.\n\n"
            f"Titel: {row['title']}\nGültig bis / Review fällig: {job['due_on'].strftime('%d.%m.%Y')}\n"
            f"Dokument öffnen: {config['base_url'].rstrip('/')}/versions/{job['version_id']}/\n\n"
            "Bitte das Prüfergebnis im DMS protokollieren. Diese Nachricht enthält keine Dokumentdatei.\n")
        try:
            smtp_send(config,recipient,subject,body,job['message_id'])
        except Exception as exc:
            status,error = failure_status(exc)
            finish(job,status,error,recipient)
        else:
            finish(job,'SENT',email=recipient)
    return True


@transaction.atomic
def retry_failed(user,notification_id):
    uid = require_settings_admin(user)
    rows = s.query("UPDATE review_notifications SET status='PENDING',next_attempt_at=clock_timestamp(),error_code='' WHERE id=%s AND status='FAILED' RETURNING id",[notification_id])
    if not rows:
        raise ValidationError('Nur eindeutig fehlgeschlagene Sendungen können wiederholt werden. Unklare Sendungen zuerst manuell prüfen.')
    mail_event('MAIL_RETRY',notification_id,'Administrativ erneut vorgemerkt',actor_id=uid)


@transaction.atomic
def set_contact_email(user,user_id,email,reason):
    uid = require_settings_admin(user)
    if email:
        validate_email(email)
    if not reason.strip():
        raise ValidationError('Eine Begründung ist erforderlich.')
    people = s.query('SELECT * FROM users WHERE id=%s FOR UPDATE',[user_id])
    if not people:
        raise ValidationError('Benutzer ist nicht vorhanden.')
    person = people[0]
    s.query('UPDATE users SET email=%s WHERE id=%s',[email,user_id])
    s.query('UPDATE auth_user SET email=%s WHERE id=%s',[email,person['auth_user_id']])
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_CONTACT_EMAIL','user',%s,%s,%s::jsonb)",[uid,str(user_id),reason,json.dumps({'before':person['email'],'after':email})])
    if email:
        rows = s.query("UPDATE review_notifications SET status='PENDING',error_code='',next_attempt_at=clock_timestamp() WHERE recipient_id=%s AND status='FAILED' AND error_code='MISSING_EMAIL' RETURNING id",[user_id])
        for row in rows:
            mail_event('MAIL_RETRY',row['id'],'Empfängeradresse ergänzt',actor_id=uid)


def send_test(user,recipient):
    uid = require_settings_admin(user)
    validate_email(recipient)
    config = load_config()
    try:
        smtp_send(config,recipient,'DMS: SMTP-Test',f'Die SMTP-Verbindung für „{APP_NAME}“ funktioniert. Diese Testnachricht enthält keine Dokumentdaten.',f'<{uuid.uuid4().hex}@ims-dms.local>')
    except Exception as exc:
        status,error = failure_status(exc)
        s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'SMTP_TEST','settings','1','SMTP-Test fehlgeschlagen',%s::jsonb)",[uid,json.dumps({'status':status,'error_code':error})])
        raise ValidationError('SMTP-Test nicht bestätigt. Server, Verschlüsselung, Zugangsdaten und Absender prüfen. Bei unklarem Ergebnis vor Wiederholung das Postfach prüfen.')
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'SMTP_TEST','settings','1','SMTP-Test erfolgreich',%s::jsonb)",[uid,json.dumps({'recipient':recipient,'status':'SENT'})])


@transaction.atomic
def save_notification_policy(user,enabled,reminder_days,reason):
    from .policies import require_qmb
    uid = require_qmb(user)
    s.query('SELECT pg_advisory_xact_lock(824010,1)')
    before = load_config()
    if not reason.strip() or not 0<=reminder_days<=3650:
        raise ValidationError('Begründung und gültiger Vorlauf erforderlich.')
    updated = dict(before,enabled=enabled,reminder_days=reminder_days)
    validate_config(updated)
    s.query('UPDATE notification_settings SET enabled=%s,reminder_days=%s,updated_at=clock_timestamp() WHERE id=1',[enabled,reminder_days])
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_REMINDER_POLICY','settings','1',%s,%s::jsonb)",[uid,reason,json.dumps({'before':{'enabled':before['enabled'],'reminder_days':before['reminder_days']},'after':{'enabled':enabled,'reminder_days':reminder_days}})])
