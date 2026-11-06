from datetime import timedelta
from email import policy
from email.parser import BytesParser
import io
import smtplib
import socketserver
import threading
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError,transaction,connection
from django.test import TestCase,Client
from django.utils import timezone
from . import tests as fixtures,notifications as n,services as s

class LocalSMTPHandler(socketserver.StreamRequestHandler):
    def answer(self,line):
        self.wfile.write(line+b'\r\n')
        self.wfile.flush()
    def handle(self):
        self.answer(b'220 localhost test SMTP')
        recipients = []
        while True:
            line = self.rfile.readline(65536)
            if not line:
                return
            command = line.upper()
            if command.startswith(b'EHLO'):
                self.answer(b'250-localhost\r\n250 SIZE 1000000')
            elif command.startswith((b'HELO',b'MAIL',b'RSET',b'NOOP')):
                self.answer(b'250 OK')
            elif command.startswith(b'RCPT'):
                recipients.append(line.decode().strip())
                self.answer(b'250 OK')
            elif command.startswith(b'DATA'):
                self.answer(b'354 End with dot')
                body = bytearray()
                while True:
                    part = self.rfile.readline(65536)
                    if part in (b'.\r\n',b'.\n',b''):
                        break
                    body.extend(part[1:] if part.startswith(b'..') else part)
                    if len(body)>1000000:
                        return
                self.server.messages.append((recipients,bytes(body)))
                self.answer(b'250 Accepted by local test server')
            elif command.startswith(b'QUIT'):
                self.answer(b'221 Bye')
                return
            else:
                self.answer(b'502 Unsupported')

class LocalSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

class NotificationTests(TestCase):
    publish = fixtures.WorkflowTests.publish
    def setUp(self):
        fixtures.WorkflowTests.setUp(self)
        self.server = LocalSMTPServer(('127.0.0.1',0),LocalSMTPHandler)
        self.server.messages = []
        thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.admin = get_user_model().objects.create_user('smtp-admin',password='TestPassword-2026!')
        s.query("INSERT INTO users(display_name,auth_user_id,settings_admin) VALUES ('SMTP-Admin',%s,true)",[self.admin.pk])
        n.set_contact_email(self.admin,s.actor(self.author),'author@example.test','Testadresse lokal')
        self.today = timezone.localdate()
        self.due = self.today+timedelta(days=5)
        s.query('UPDATE document_versions SET next_review_on=%s WHERE id=%s',[self.due,self.vid])
        self.publish()
        self.configure()

    def configure(self,**overrides):
        data = n.public_config(n.load_config()) | {'password':'','clear_password':False,'reason':'Lokaler SMTP-Funktionstest',
            'enabled':True,'smtp_host':'127.0.0.1','smtp_port':self.server.server_address[1],
            'smtp_security':'NONE','smtp_username':'','sender_email':'dms@example.test','base_url':'http://dms.example.test'}
        data.update(overrides)
        enabled = data['enabled']
        days = data['reminder_days']
        if not enabled:
            n.save_notification_policy(self.reviewer,False,days,'Test: Versand pausieren')
        n.save_config(self.admin,data)
        n.save_notification_policy(self.reviewer,enabled,days,'Test: fachliche Erinnerungsregeln')

    def dispatch_pending(self,today):
        # This fixture has no QMB mailbox; team tests verify actual QMB delivery.
        processed = False
        for _ in range(20):
            if not n.dispatch_one(today):
                break
            processed = True
        return processed

    def test_legacy_expiry_does_not_suppress_due_mail_for_visible_release(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from . import storage
        vid = s.create_document(self.author,dict(number='EXPIRED-MAIL',title='Abgelaufene aktuelle Fassung',
            document_type='Prozess',department=self.dep,change_summary='Regression',
            effective_from=timezone.now()-timedelta(days=10),next_review_on=self.today))
        storage.upload(self.author,vid,SimpleUploadedFile('expired.txt',b'Fixture'))
        s.query('UPDATE document_versions SET valid_until=%s WHERE id=%s',[timezone.now()-timedelta(days=1),vid])
        s.transition(self.author,vid,'submit','Prüfen')
        s.transition(self.reviewer,vid,'accept','Geprüft')
        s.transition(self.reviewer,vid,'accept','Freigegeben')
        n.queue_due(self.today)
        self.assertTrue(s.query("SELECT 1 FROM review_notifications WHERE version_id=%s AND kind='DUE'",[vid]))
        self.dispatch_pending(self.today)
        self.assertTrue(any(b'EXPIRED-MAIL' in raw for recipients,raw in self.server.messages))

    def test_real_smtp_before_and_due_once_each_to_responsible_author(self):
        self.assertEqual(n.queue_due(self.today),2)
        self.assertTrue(self.dispatch_pending(self.today))
        self.assertEqual(n.queue_due(self.today+timedelta(days=1)),0)
        self.assertFalse(self.dispatch_pending(self.today+timedelta(days=1)))
        self.assertEqual(len(self.server.messages),1)
        recipients,raw = self.server.messages[0]
        self.assertIn('author@example.test',' '.join(recipients))
        message = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertIn('IT-001',str(message['Subject']))
        self.assertIn('/versions/',message.get_body(preferencelist=('plain',)).get_content())
        self.assertEqual(n.queue_due(self.due),2)
        self.assertTrue(self.dispatch_pending(self.due))
        self.assertEqual(n.queue_due(self.due+timedelta(days=1)),0)
        self.assertEqual(len(self.server.messages),2)
        self.assertEqual(s.query("SELECT count(*) AS n FROM review_notifications WHERE status='SENT'")[0]['n'],2)

    def test_no_early_or_disabled_mail(self):
        self.configure(reminder_days=2)
        self.assertEqual(n.queue_due(self.today),0)
        self.configure(enabled=False)
        self.assertEqual(n.queue_due(self.due),0)
        self.assertFalse(self.dispatch_pending(self.due))
        self.assertEqual(self.server.messages,[])

    def test_expired_documents_generate_only_due_message_after_missed_schedule(self):
        self.assertEqual(n.queue_due(self.due+timedelta(days=10)),2)
        self.assertTrue(self.dispatch_pending(self.due+timedelta(days=10)))
        self.assertEqual(s.query("SELECT kind FROM review_notifications WHERE recipient_kind='OWNER'")[0]['kind'],'DUE')
        self.assertEqual(len(self.server.messages),1)

    def test_completed_review_cancels_old_reminder(self):
        n.queue_due(self.today)
        s.record_review(self.reviewer,self.vid,'UNCHANGED','Erneut geprüft')
        self.dispatch_pending(self.today)
        self.assertEqual(s.query("SELECT status FROM review_notifications WHERE recipient_kind='OWNER'")[0]['status'],'CANCELLED')
        self.assertEqual(self.server.messages,[])

    def test_withdrawal_and_removed_access_stop_queued_mail(self):
        n.queue_due(self.today)
        s.change_access(self.author,self.vid,'EXPLICIT',[s.actor(self.author),s.actor(self.approver)],[],'Begrenzen')
        s.lifecycle_action(self.reviewer,self.vid,'withdraw','Nicht mehr gültig',True)
        self.dispatch_pending(self.today)
        self.assertEqual(s.query("SELECT status FROM review_notifications WHERE recipient_kind='OWNER'")[0]['status'],'CANCELLED')
        self.assertEqual(self.server.messages,[])

    def test_missing_address_is_visible_and_fixed_address_requeues(self):
        n.set_contact_email(self.admin,s.actor(self.author),'','Adresse entfernen')
        n.queue_due(self.today)
        self.dispatch_pending(self.today)
        self.assertEqual(s.query("SELECT error_code FROM review_notifications WHERE recipient_kind='OWNER'")[0]['error_code'],'MISSING_EMAIL')
        n.set_contact_email(self.admin,s.actor(self.author),'fixed@example.test','Adresse korrigieren')
        self.dispatch_pending(self.today)
        self.assertEqual(len(self.server.messages),1)
        self.assertIn('fixed@example.test',' '.join(self.server.messages[0][0]))

    def test_unknown_smtp_result_is_not_automatically_resent(self):
        n.queue_due(self.today)
        with patch('dms.notifications.smtp_send',side_effect=TimeoutError):
            self.dispatch_pending(self.today)
        job = s.query("SELECT * FROM review_notifications WHERE recipient_kind='OWNER'")[0]
        self.assertEqual(job['status'],'UNCERTAIN')
        self.assertEqual(n.queue_due(self.today),0)
        self.assertFalse(self.dispatch_pending(self.today))
        with self.assertRaises(ValidationError):
            n.retry_failed(self.admin,job['id'])

    def test_known_smtp_rejection_can_be_retried_after_settings_fix(self):
        n.queue_due(self.today)
        with patch('dms.notifications.smtp_send',side_effect=smtplib.SMTPAuthenticationError(535,b'Test refusal')):
            self.dispatch_pending(self.today)
        self.assertEqual(s.query("SELECT status FROM review_notifications WHERE recipient_kind='OWNER'")[0]['status'],'FAILED')
        self.configure(reason='SMTP korrigiert')
        self.dispatch_pending(self.today)
        self.assertEqual(len(self.server.messages),1)

    def test_lost_worker_lease_becomes_uncertain(self):
        n.queue_due(self.today)
        while n.claim():
            pass
        s.query("UPDATE review_notifications SET claimed_at=clock_timestamp()-interval '6 minutes'")
        self.assertIsNone(n.claim())
        self.assertEqual(s.query("SELECT status FROM review_notifications WHERE recipient_kind='OWNER'")[0]['status'],'UNCERTAIN')

    def test_changed_lead_time_defers_and_later_releases_pending_job(self):
        n.queue_due(self.today)
        self.configure(reminder_days=2)
        self.dispatch_pending(self.today)
        self.assertEqual(self.server.messages,[])
        self.configure(reminder_days=10)
        n.queue_due(self.today)
        self.dispatch_pending(self.today)
        self.assertEqual(len(self.server.messages),1)

    def test_smtp_password_is_encrypted_hidden_and_not_in_audit(self):
        password = 'Unique-SMTP-secret-not-for-logs'
        self.configure(enabled=False,smtp_username='smtp-user',password=password)
        config = n.load_config()
        self.assertNotEqual(config['password_ciphertext'],password)
        self.assertEqual(n.cipher().decrypt(config['password_ciphertext'].encode()).decode(),password)
        self.client.force_login(self.admin)
        response = self.client.get('/settings/email/')
        self.assertNotContains(response,password)
        self.assertNotContains(response,config['password_ciphertext'])
        self.assertNotIn(password,str(s.query("SELECT details FROM audit_events WHERE action='CHANGE_MAIL_SETTINGS'")))
        self.configure(enabled=False,smtp_username='smtp-user')
        self.assertEqual(n.load_config()['password_ciphertext'],config['password_ciphertext'])

    def test_admin_permissions_csrf_and_contact_ui(self):
        self.client.force_login(self.author)
        self.assertEqual(self.client.get('/settings/email/').status_code,403)
        self.assertEqual(self.client.post('/settings/email/test/',{'recipient':'test@example.test'}).status_code,403)
        self.assertEqual(self.client.post('/settings/contacts/',{'user_id':s.actor(self.author),'email':'changed@example.test','reason':'x'}).status_code,403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/settings/email/'),'SMTP-Server')
        self.assertContains(self.client.get('/settings/contacts/'),'author@example.test')
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post('/settings/email/',{}).status_code,403)
        self.assertEqual(self.client.get('/settings/email/test/').status_code,405)

    def test_explicit_test_mail_does_not_enable_automatic_reminders(self):
        self.configure(enabled=False)
        n.send_test(self.admin,'test@example.test')
        self.assertFalse(n.load_config()['enabled'])
        self.assertEqual(len(self.server.messages),1)

    def test_worker_role_can_send_without_reading_password_hashes_or_document_files(self):
        from django.conf import settings
        with connection.cursor() as cursor:
            cursor.execute('CREATE ROLE ims_notify_test NOLOGIN')
            cursor.execute((settings.BASE_DIR/'db/notification_grants.sql').read_text().replace(':"notification_role"','ims_notify_test').replace(':"database_name"',connection.settings_dict['NAME']))
            cursor.execute('SET LOCAL ROLE ims_notify_test')
        self.assertEqual(n.queue_due(self.today),2)
        self.assertTrue(self.dispatch_pending(self.today))
        self.assertEqual(len(self.server.messages),1)
        for sql in ['SELECT password FROM auth_user','SELECT * FROM file_text_indexes',"UPDATE notification_settings SET enabled=false"]:
            with self.assertRaises(DatabaseError),transaction.atomic():
                s.query(sql)

    def test_new_review_cycle_gets_new_reminders_without_reusing_old_deadline(self):
        n.queue_due(self.today)
        self.dispatch_pending(self.today)
        s.record_review(self.reviewer,self.vid,'UNCHANGED','Richtigkeit erneut bestätigt')
        new_due = s.visible_versions(self.author)[0]['review_due_on']
        self.assertEqual(n.queue_due(new_due-timedelta(days=5)),2)
        self.dispatch_pending(new_due-timedelta(days=5))
        self.assertEqual(len(self.server.messages),2)
        self.assertEqual(len(s.query('SELECT DISTINCT due_on FROM review_notifications')),2)

    def test_revoked_owner_access_is_checked_again_and_restoration_can_requeue(self):
        n.queue_due(self.today)
        s.query('DELETE FROM role_assignments WHERE user_id=%s',[s.actor(self.author)])
        self.dispatch_pending(self.today)
        self.assertEqual(self.server.messages,[])
        self.assertEqual(s.query("SELECT error_code FROM review_notifications WHERE recipient_kind='OWNER'")[0]['error_code'],'NO_ACCESS')
        s.query("INSERT INTO role_assignments(user_id,role,department_id) VALUES (%s,'AUTHOR',%s)",[s.actor(self.author),self.dep])
        self.assertEqual(n.queue_due(self.today),1)
        self.dispatch_pending(self.today)
        self.assertEqual(len(self.server.messages),1)

    def test_smtp_settings_post_preserves_password_spaces_and_sends_nothing(self):
        self.client.force_login(self.admin)
        data = n.public_config(n.load_config()) | {'enabled':'','password':' padded SMTP secret ','clear_password':'','reason':'Konfiguration über Oberfläche'}
        response = self.client.post('/settings/email/',data)
        self.assertEqual(response.status_code,302)
        config = n.load_config()
        self.assertTrue(config['enabled'])  # IT cannot change QMB reminder activation.
        self.assertEqual(n.cipher().decrypt(config['password_ciphertext'].encode()).decode(),' padded SMTP secret ')
        self.assertEqual(self.server.messages,[])

    def test_profile_email_correction_recovers_only_missing_address_failures(self):
        n.set_contact_email(self.admin,s.actor(self.author),'','Test: Adresse fehlt')
        n.queue_due(self.today);self.dispatch_pending(self.today)
        uid=s.actor(self.author)
        job=s.query("SELECT id,status,error_code FROM review_notifications WHERE recipient_id=%s",[uid])[0]
        self.assertEqual((job['status'],job['error_code']),('FAILED','MISSING_EMAIL'))
        self.client.force_login(self.admin)
        response=self.client.post(f'/settings/users/{uid}/profile/',{'display_name':'Autor korrigiert','email':'fixed@example.test','reason':'Adresse ergänzen'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(s.query('SELECT status FROM review_notifications WHERE id=%s',[job['id']])[0]['status'],'PENDING')
        self.dispatch_pending(self.today)
        self.assertEqual(s.query('SELECT status,recipient_email FROM review_notifications WHERE id=%s',[job['id']])[0],{'status':'SENT','recipient_email':'fixed@example.test'})
        for status in ('SENT','UNCERTAIN'):
            s.query('UPDATE review_notifications SET status=%s WHERE id=%s',[status,job['id']])
            self.client.post(f'/settings/users/{uid}/profile/',{'display_name':'Autor korrigiert','email':'other@example.test','reason':'Kontakt ändern'})
            self.assertEqual(s.query('SELECT status FROM review_notifications WHERE id=%s',[job['id']])[0]['status'],status)
        self.assertEqual(len(s.query("SELECT 1 FROM audit_events WHERE action='MAIL_RETRY' AND object_id=%s",[str(job['id'])])),1)
