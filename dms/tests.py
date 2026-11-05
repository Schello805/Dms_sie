from datetime import timedelta
import tempfile
from pathlib import Path
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from . import storage
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase, Client
from django.utils import timezone
from . import services as s

class WorkflowTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=Path(self.media.name))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.dep = s.query("INSERT INTO departments(code,name) VALUES ('IT','IT') RETURNING id")[0]['id']
        self.people = []
        for name, role in [('author','AUTHOR'),('reviewer','REVIEWER'),('approver','REVIEWER'),('reader','READER'),('outsider',None)]:
            user = get_user_model().objects.create_user(name,password='TestPassword-2026!')
            uid = s.query('INSERT INTO users(display_name,auth_user_id) VALUES (%s,%s) RETURNING id',[name,user.pk])[0]['id']
            if role:
                s.query('INSERT INTO role_assignments(user_id,role,department_id) VALUES (%s,%s,%s)',[uid,role,self.dep])
            self.people.append(user)
        self.author,self.reviewer,self.approver,self.reader,self.outsider = self.people
        s.query("UPDATE users SET qmb_role='PRIMARY' WHERE auth_user_id=%s",[self.reviewer.pk])
        self.vid = s.create_document(self.author,dict(number='IT-001',document_type='Richtlinie',department=self.dep,title='Testdokument',change_summary='Erstfassung',effective_from=timezone.now()-timedelta(days=1),next_review_on=timezone.localdate()+timedelta(days=365)))

        storage.upload(self.author,self.vid,SimpleUploadedFile('test.txt',b'Originalinhalt'))

    def publish(self):
        s.transition(self.author,self.vid,'submit','Prüfung erbeten')
        s.transition(self.reviewer,self.vid,'accept','Fachlich geprüft')
        s.transition(self.reviewer,self.vid,'accept','Freigegeben')

    def test_independent_workflow_and_audit(self):
        self.assertEqual(s.visible_versions(self.reader),[])
        self.publish()
        self.assertEqual(s.visible_versions(self.reader)[0]['status'],'APPROVED')
        self.assertEqual(len(s.query('SELECT * FROM approval_decisions')),2)
        self.assertEqual(len(s.query("SELECT * FROM audit_events WHERE action='TRANSITION'")),3)
        with self.assertRaises(DatabaseError), transaction.atomic():
            s.query("UPDATE document_versions SET title='Manipuliert' WHERE id=%s",[self.vid])

    def test_no_self_review_even_with_role(self):
        uid = s.actor(self.author)
        s.query("INSERT INTO role_assignments(user_id,role) VALUES (%s,'REVIEWER')",[uid])
        s.transition(self.author,self.vid,'submit','Einreichen')
        with self.assertRaises(PermissionDenied):
            s.transition(self.author,self.vid,'accept','Selbstprüfung')
        self.assertEqual(s.query('SELECT * FROM approval_decisions'),[])

    def test_rejected_cycle_does_not_supply_old_review(self):
        s.transition(self.author,self.vid,'submit','Zyklus eins')
        s.transition(self.reviewer,self.vid,'accept','Geprüft')
        s.transition(self.reviewer,self.vid,'return','Änderungen erforderlich')
        s.transition(self.author,self.vid,'submit','Zyklus zwei')
        with self.assertRaises(PermissionDenied):
            s.transition(self.approver,self.vid,'accept','Zu früh')
        self.assertEqual(s.query('SELECT status FROM document_versions')[0]['status'],'IN_REVIEW')

    def test_no_direct_release_without_decisions(self):
        s.transition(self.author,self.vid,'submit','Prüfen')
        s.transition(self.reviewer,self.vid,'accept','Geprüft')
        with self.assertRaises(DatabaseError), transaction.atomic():
            s.query("UPDATE document_versions SET status='APPROVED' WHERE id=%s",[self.vid])

    def test_permissions_and_post_only(self):
        with self.assertRaises(PermissionDenied):
            s.get_version(self.outsider,self.vid)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/').status_code,403)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/action/').status_code,405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.author)
        self.assertEqual(csrf.post(f'/versions/{self.vid}/action/',{'action':'submit','comment':'x'}).status_code,403)

    def test_page_renders(self):
        self.client.force_login(self.author)
        for url in ['/', '/new/', f'/versions/{self.vid}/']:
            self.assertEqual(self.client.get(url).status_code,200)

    def test_audit_is_append_only(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            s.query("DELETE FROM audit_events")

    def test_blank_reason_rolls_back(self):
        with self.assertRaises(ValidationError):
            s.transition(self.author,self.vid,'submit',' ')
        self.assertEqual(s.query('SELECT * FROM workflow_instances'),[])

    def test_integrity_and_download_permissions(self):
        self.publish()
        f = s.query('SELECT * FROM file_objects')[0]
        self.assertEqual(storage.download(self.reader,self.vid,f['id'])[1],b'Originalinhalt')
        with self.assertRaises(PermissionDenied):
            storage.download(self.outsider,self.vid,f['id'])
        (Path(self.media.name)/f['storage_key']).write_bytes(b'Manipuliert')
        with self.assertRaises(ValidationError):
            storage.download(self.reader,self.vid,f['id'])
        self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='INTEGRITY_FAILURE'"))

    def test_new_revision_preserves_release(self):
        self.publish()
        vid = s.new_revision(self.author,self.vid)
        self.assertNotEqual(vid,self.vid)
        self.assertEqual(s.get_version(self.author,vid)[1]['major'],2)
        self.assertEqual(s.visible_versions(self.reader)[0]['id'],self.vid)
        with self.assertRaises(ValidationError):
            s.new_revision(self.author,self.vid)

    def test_upload_blocked_after_submission(self):
        s.transition(self.author,self.vid,'submit','Prüfen')
        with self.assertRaises(ValidationError):
            storage.upload(self.author,self.vid,SimpleUploadedFile('new.txt',b'Neu'))
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM version_files WHERE version_id=%s',[self.vid])

    def test_revision_can_replace_file_without_changing_old_release(self):
        self.publish()
        vid = s.new_revision(self.author,self.vid)
        old_file = s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        s.remove_file(self.author,vid,old_file,'Datei wird ersetzt')
        self.assertEqual(storage.download(self.reader,self.vid,old_file)[1],b'Originalinhalt')
        self.assertEqual(s.query('SELECT * FROM version_files WHERE version_id=%s',[vid]),[])

    def test_future_release_and_successor_visibility(self):
        self.publish()
        vid = s.new_revision(self.author,self.vid)
        data = dict(title='Nachfolger',change_summary='Neue Fassung',effective_from=timezone.now()+timedelta(days=1),next_review_on=timezone.localdate()+timedelta(days=365))
        s.edit_draft(self.author,vid,data)
        s.transition(self.author,vid,'submit','Prüfen')
        s.transition(self.reviewer,vid,'accept','Geprüft')
        s.transition(self.reviewer,vid,'accept','Freigabe')
        self.assertEqual([r['id'] for r in s.visible_versions(self.reader)],[self.vid])
        with self.assertRaises(PermissionDenied):
            s.get_version(self.reader,vid)

    def test_effective_successor_hides_previous_release(self):
        self.publish()
        vid = s.new_revision(self.author,self.vid)
        s.edit_draft(self.author,vid,dict(title='Nachfolger',change_summary='Neue Fassung',effective_from=timezone.now()-timedelta(hours=1),next_review_on=timezone.localdate()+timedelta(days=365)))
        s.transition(self.author,vid,'submit','Prüfen')
        s.transition(self.reviewer,vid,'accept','Geprüft')
        s.transition(self.reviewer,vid,'accept','Freigabe')
        self.assertEqual([r['id'] for r in s.visible_versions(self.reader)],[vid])
        with self.assertRaises(PermissionDenied):
            s.get_version(self.reader,self.vid)

    def enable_runtime_role(self):
        from django.db import connection
        from django.conf import settings
        with connection.cursor() as cursor:
            cursor.execute('CREATE ROLE ims_dms_test_runtime NOLOGIN')
            grants = (settings.BASE_DIR/'db/runtime_grants.sql').read_text().replace(':"runtime_role"','ims_dms_test_runtime')
            cursor.execute(grants)
            cursor.execute('SET LOCAL ROLE ims_dms_test_runtime')

    def test_workflow_and_revision_with_restricted_database_role(self):
        self.enable_runtime_role()
        self.publish()
        vid = s.new_revision(self.author,self.vid)
        old_file = s.query('SELECT file_id FROM version_files WHERE version_id=%s',[vid])[0]['file_id']
        s.remove_file(self.author,vid,old_file,'Ersetzen')
        storage.upload(self.author,vid,SimpleUploadedFile('neu.txt',b'Neue Revision'))
        s.edit_draft(self.author,vid,dict(title='Neu',change_summary='Revision',effective_from=timezone.now()-timedelta(hours=1),next_review_on=timezone.localdate()+timedelta(days=365)))
        s.transition(self.author,vid,'submit','Prüfen')
        s.transition(self.reviewer,vid,'accept','Geprüft')
        s.transition(self.reviewer,vid,'accept','Freigabe')
        self.assertEqual([r['id'] for r in s.visible_versions(self.reader)],[vid])

    def test_runtime_role_cannot_truncate_or_grant_itself_roles(self):
        self.enable_runtime_role()
        for sql in ['TRUNCATE audit_events',"INSERT INTO role_assignments(user_id,role) SELECT id,'APPROVER' FROM users LIMIT 1"]:
            with self.assertRaises(DatabaseError),transaction.atomic():
                s.query(sql)

    def test_empty_document_cannot_be_submitted(self):
        file_id = s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        s.remove_file(self.author,self.vid,file_id,'Keine Datei')
        with self.assertRaises(ValidationError):
            s.transition(self.author,self.vid,'submit','Einreichen')

    def test_norm_mapping_is_frozen_and_filter_does_not_expand_access(self):
        standard = s.query("INSERT INTO standards(name,edition) VALUES ('Testnorm','Demo') RETURNING id")[0]['id']
        reference = s.query("INSERT INTO standard_references(standard_id,reference,label) VALUES (%s,'X','Testreferenz') RETURNING id",[standard])[0]['id']
        data = dict(title='Mit Normbezug',change_summary='Zuordnung ergänzt',effective_from=timezone.now()-timedelta(days=1),next_review_on=timezone.localdate()+timedelta(days=365),standard_references=[reference],applicable_departments=[])
        s.edit_draft(self.author,self.vid,data)
        self.assertEqual(len(s.visible_versions(self.author,standard=str(standard),department=str(self.dep))),1)
        self.assertEqual(s.visible_versions(self.outsider,standard=str(standard)),[])
        self.assertEqual(s.visible_versions(self.author,standard='invalid'),[])
        before = s.fingerprint(s.get_version(self.author,self.vid)[1])
        self.publish()
        self.assertEqual(before,s.fingerprint(s.get_version(self.author,self.vid)[1]))
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM version_standard_links WHERE version_id=%s',[self.vid])

    def test_periodic_review_preserves_version_and_moves_due_date(self):
        due = timezone.localdate()-timedelta(days=1)
        s.query('UPDATE document_versions SET next_review_on=%s WHERE id=%s',[due,self.vid])
        self.publish()
        self.assertEqual(len(s.visible_versions(self.reviewer,due_only=True)),1)
        next_date = timezone.localdate()+timedelta(days=365)
        s.record_review(self.reviewer,self.vid,'UNCHANGED','Weiterhin geeignet',next_date)
        self.assertEqual(s.visible_versions(self.reviewer,due_only=True),[])
        self.assertEqual(s.visible_versions(self.reviewer)[0]['review_due_on'],next_date)
        self.assertEqual(s.get_version(self.reviewer,self.vid)[1]['next_review_on'],due)
        self.assertEqual(len(s.query('SELECT * FROM document_versions')),1)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query("UPDATE periodic_reviews SET rationale='Geändert'")

    def test_review_requiring_revision_stays_actionable(self):
        self.publish()
        s.record_review(self.reviewer,self.vid,'REVISION_REQUIRED','Prozess hat sich geändert',timezone.localdate()+timedelta(days=10))
        self.assertEqual(len(s.visible_versions(self.reviewer,due_only=True)),1)
        self.assertEqual(s.get_version(self.reader,self.vid)[1]['status'],'APPROVED')

    def test_review_requires_role_and_future_date(self):
        self.publish()
        for user in [self.reader,self.author,self.outsider]:
            with self.assertRaises(PermissionDenied):
                s.record_review(user,self.vid,'UNCHANGED','Prüfung',timezone.localdate()+timedelta(days=1))
        for date in [timezone.localdate()]:
            with self.assertRaises(ValidationError):
                s.record_review(self.reviewer,self.vid,'UNCHANGED','Prüfung',date)

    def test_review_http_csrf_and_history(self):
        self.publish()
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/review/').status_code,405)
        response = self.client.post(f'/versions/{self.vid}/review/',{'result':'UNCHANGED','rationale':'Periodisch geprüft','next_review_on':str(timezone.localdate()+timedelta(days=365))})
        self.assertEqual(response.status_code,302)
        self.assertContains(self.client.get(f'/versions/{self.vid}/'),'Periodisch geprüft')
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.reviewer)
        self.assertEqual(csrf.post(f'/versions/{self.vid}/review/',{}).status_code,403)

    def test_review_and_mapping_with_restricted_database_role(self):
        standard = s.query("INSERT INTO standards(name,edition) VALUES ('Testnorm','Demo') RETURNING id")[0]['id']
        reference = s.query("INSERT INTO standard_references(standard_id,reference,label) VALUES (%s,'X','Testreferenz') RETURNING id",[standard])[0]['id']
        self.enable_runtime_role()
        s.edit_draft(self.author,self.vid,dict(title='Normbezug',change_summary='Zuordnung',effective_from=timezone.now()-timedelta(days=1),next_review_on=timezone.localdate(),standard_references=[reference],applicable_departments=[]))
        self.publish()
        s.record_review(self.reviewer,self.vid,'UNCHANGED','Weiter gültig',timezone.localdate()+timedelta(days=365))
        self.assertEqual(s.visible_versions(self.reviewer,due_only=True),[])
        self.assertEqual(len(s.visible_versions(self.reader,standard=str(standard))),1)

    def test_development_seed_is_repeatable_and_keeps_passwords(self):
        import io
        import os
        from unittest.mock import patch
        from django.core.management import call_command
        with patch.dict(os.environ,{'DMS_DEBUG':'1','DMS_DEMO_PASSWORD':'Original-Development-Password-2026!'}):
            call_command('seed_dev',stdout=io.StringIO())
        count = s.query('SELECT count(*) AS n FROM documents')[0]['n']
        with patch.dict(os.environ,{'DMS_DEBUG':'1','DMS_DEMO_PASSWORD':'Different-Development-Password-2026!'}):
            call_command('seed_dev',stdout=io.StringIO())
        self.assertEqual(s.query('SELECT count(*) AS n FROM documents')[0]['n'],count)
        self.assertTrue(get_user_model().objects.get(username='autor').check_password('Original-Development-Password-2026!'))
        demo = s.query("SELECT v.id FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE d.number='DEMO-003'")[0]['id']
        self.assertEqual(len(s.query('SELECT * FROM version_standard_links WHERE version_id=%s',[demo])),3)

    def test_minor_then_major_numbering_and_old_source_rejection(self):
        self.publish()
        minor = s.new_revision(self.author,self.vid,kind='minor',reason='Begriffe präzisieren')
        v = s.get_version(self.author,minor)[1]
        self.assertEqual((v['major'],v['minor']),(1,1))
        self.assertEqual(v['change_summary'],'Begriffe präzisieren')
        s.edit_draft(self.author,minor,dict(title='Präzisierte Fassung',change_summary='Begriffe präzisiert',effective_from=timezone.now()-timedelta(hours=1),next_review_on=timezone.localdate()+timedelta(days=365)))
        s.transition(self.author,minor,'submit','Prüfung erbeten')
        s.transition(self.reviewer,minor,'accept','Geprüft')
        s.transition(self.reviewer,minor,'accept','Freigegeben')
        with self.assertRaises(ValidationError):
            s.new_revision(self.author,self.vid,kind='minor',reason='Veraltete Quelle')
        major = s.new_revision(self.author,minor,kind='major',reason='Prozess neu strukturieren')
        v = s.get_version(self.author,major)[1]
        self.assertEqual((v['major'],v['minor']),(2,0))
        self.assertEqual([r['id'] for r in s.visible_versions(self.reader)],[minor])

    def test_history_roles_and_recorded_decisions(self):
        self.publish()
        minor = s.new_revision(self.author,self.vid,kind='minor',reason='Begriffe präzisieren')
        v,versions,decisions = s.version_history(self.reviewer,minor)
        self.assertEqual([r['id'] for r in versions],[minor,self.vid])
        self.assertEqual(len(decisions),2)
        self.assertEqual({r['actor_name'] for r in decisions},{'reviewer'})
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(f'/versions/{minor}/history/'),'Versionshistorie')
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/history/').status_code,403)

    def test_revision_endpoint_requires_reason_and_post(self):
        self.publish()
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/revision/').status_code,405)
        self.client.post(f'/versions/{self.vid}/revision/',{'kind':'minor','reason':''})
        self.assertEqual(len(s.query('SELECT * FROM document_versions')),1)
        self.client.post(f'/versions/{self.vid}/revision/',{'kind':'minor','reason':'Redaktionelle Präzisierung'})
        self.assertEqual(len(s.query('SELECT * FROM document_versions')),2)

    def test_minor_history_with_runtime_database_role(self):
        self.enable_runtime_role()
        self.publish()
        minor = s.new_revision(self.author,self.vid,kind='minor',reason='Ergänzung')
        v,versions,decisions = s.version_history(self.author,minor)
        self.assertEqual(len(versions),2)
        self.assertEqual(len(decisions),2)

    @override_settings(DEBUG=False,SESSION_COOKIE_SECURE=True,CSRF_COOKIE_SECURE=True,SECURE_SSL_REDIRECT=True)
    def test_https_login_keeps_secure_cookies(self):
        response = self.client.get('/login/',secure=True)
        self.assertTrue(response.cookies['csrftoken']['secure'])
        response = self.client.post('/login/',{'username':'author','password':'TestPassword-2026!'},secure=True)
        self.assertEqual(response.status_code,302)
        self.assertTrue(response.cookies['sessionid']['secure'])
        self.assertEqual(self.client.get('/login/').status_code,301)

    def make_group(self,name,user,role=None,document_id=None):
        gid = s.query('INSERT INTO dms_groups(name) VALUES (%s) RETURNING id',[name])[0]['id']
        s.query('INSERT INTO group_memberships(group_id,user_id) VALUES (%s,%s)',[gid,s.actor(user)])
        if role:
            s.query('INSERT INTO role_assignments(group_id,role,department_id,document_id) VALUES (%s,%s,%s,%s)',[gid,role,None if document_id else self.dep,document_id])
        return gid

    def test_group_role_and_membership_revocation_are_immediate(self):
        self.publish()
        gid = self.make_group('IT-Leser',self.outsider,'READER')
        self.assertEqual(len(s.visible_versions(self.outsider)),1)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/',follow=True).status_code,200)
        s.query('DELETE FROM group_memberships WHERE group_id=%s',[gid])
        self.assertEqual(s.visible_versions(self.outsider),[])
        self.assertEqual(self.client.get(f'/versions/{self.vid}/').status_code,403)

    def test_explicit_access_is_additional_to_roles_and_controls_downloads(self):
        self.publish()
        doc = s.get_version(self.author,self.vid)[1]['document_id']
        s.change_access(self.author,self.vid,'EXPLICIT',[s.actor(self.author),s.actor(self.outsider)],[],'Vertraulichen Personenkreis festlegen')
        self.assertEqual(s.visible_versions(self.reader),[])
        self.assertEqual(s.visible_versions(self.outsider),[])
        f = s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        with self.assertRaises(PermissionDenied):
            storage.download(self.reader,self.vid,f)
        gid = self.make_group('Freigegebene Leser',self.reader)
        s.change_access(self.author,self.vid,'EXPLICIT',[s.actor(self.author)],[gid],'Lesergruppe ergänzen')
        self.assertEqual(storage.download(self.reader,self.vid,f)[1],b'Originalinhalt')
        s.query('UPDATE dms_groups SET active=false WHERE id=%s',[gid])
        with self.assertRaises(PermissionDenied):
            storage.download(self.reader,self.vid,f)
        self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='CHANGE_ACCESS'"))

    def test_confidential_classification_requires_explicit_access(self):
        data = dict(title='Vertraulich',change_summary='Klassifiziert',effective_from=timezone.now()-timedelta(days=1),next_review_on=timezone.localdate()+timedelta(days=365),classification='CONFIDENTIAL')
        s.edit_draft(self.author,self.vid,data)
        self.assertEqual(s.visible_versions(self.outsider),[])
        self.assertEqual(s.visible_versions(self.approver),[])
        s.change_access(self.author,self.vid,'DEPARTMENT',[s.actor(x) for x in [self.author,self.reviewer,self.approver]],[],'Vertraulichen Prüfkreis festlegen')
        self.publish()
        self.assertEqual(s.visible_versions(self.reader),[])
        s.change_access(self.author,self.vid,'DEPARTMENT',[s.actor(x) for x in [self.author,self.reviewer,self.approver,self.reader]],[],'Leser ausdrücklich freigeben')
        self.assertEqual(len(s.visible_versions(self.reader)),1)

    def test_document_role_does_not_grant_access_to_other_documents(self):
        self.publish()
        doc = s.get_version(self.author,self.vid)[1]['document_id']
        self.make_group('Dokumentprüfer',self.outsider,'REVIEWER',doc)
        self.assertTrue(s.allowed(s.actor(self.outsider),self.dep,'REVIEWER',doc))
        self.assertFalse(s.allowed(s.actor(self.outsider),self.dep,'REVIEWER'))
        other = s.create_document(self.author,dict(number='IT-002',document_type='Prozess',department=self.dep,title='Anderes Dokument',change_summary='Erstfassung',effective_from=timezone.now(),next_review_on=timezone.localdate()))
        with self.assertRaises(PermissionDenied):
            s.get_version(self.outsider,other)
        self.assertEqual([v['id'] for v in s.visible_versions(self.outsider)],[self.vid])

    def test_access_self_lockout_rolls_back_without_audit_change(self):
        before = s.access_policy(s.get_version(self.author,self.vid)[1]['document_id'])
        with self.assertRaises(ValidationError):
            s.change_access(self.author,self.vid,'EXPLICIT',[],[],'Unabsichtliche Sperre')
        self.assertEqual(s.access_policy(s.get_version(self.author,self.vid)[1]['document_id']),before)
        self.assertEqual(s.query("SELECT * FROM audit_events WHERE action='CHANGE_ACCESS'"),[])

    def test_history_does_not_leak_confidential_sibling_version(self):
        self.publish()
        vid = s.new_revision(self.author,self.vid,kind='minor',reason='Vertrauliche Erweiterung')
        s.edit_draft(self.author,vid,dict(title='Geheime Erweiterung',change_summary='Vertraulich',effective_from=timezone.now(),next_review_on=timezone.localdate(),classification='RESTRICTED'))
        v,versions,decisions = s.version_history(self.approver,self.vid)
        self.assertEqual([row['id'] for row in versions],[self.vid])
        self.client.force_login(self.approver)
        self.assertNotContains(self.client.get(f'/versions/{self.vid}/history/'),'Geheime Erweiterung',status_code=403)

    def test_access_ui_post_and_runtime_role(self):
        self.enable_runtime_role()
        self.publish()
        self.client.force_login(self.author)
        self.assertContains(self.client.get(f'/versions/{self.vid}/access/'),'Dokumentzugriff')
        response = self.client.post(f'/versions/{self.vid}/access/',{'access_mode':'EXPLICIT','users':[s.actor(self.author),s.actor(self.reader)],'reason':'Nur festgelegte Personen'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(len(s.visible_versions(self.reader)),1)
        self.assertEqual(s.visible_versions(self.approver),[])
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query("INSERT INTO dms_groups(name) VALUES ('Unzulässig')")
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM group_memberships')

    def test_group_cli_is_audited_and_group_authorship_works(self):
        import io
        from django.core.management import call_command
        output = io.StringIO()
        call_command('manage_group','create','IT-Autoren',reason='Testgruppe',stdout=output)
        call_command('manage_group','add-member','IT-Autoren',user='outsider',reason='Zuordnung',stdout=output)
        call_command('manage_group','grant','IT-Autoren',role='AUTHOR',department='IT',reason='Autorenrolle',stdout=output)
        self.assertTrue(s.allowed(s.actor(self.outsider),self.dep,'AUTHOR'))
        self.client.force_login(self.outsider)
        self.assertContains(self.client.get('/new/'),'IT')
        call_command('manage_group','disable','IT-Autoren',reason='Gruppe sperren',stdout=output)
        self.assertFalse(s.allowed(s.actor(self.outsider),self.dep,'AUTHOR'))
        self.assertEqual(len(s.query("SELECT * FROM audit_events WHERE action='GROUP_ADMIN'")),4)

    def test_role_assignment_requires_exactly_one_subject_and_scope(self):
        gid = self.make_group('Testgruppe',self.outsider)
        for sql,params in [
            ("INSERT INTO role_assignments(role) VALUES ('READER')",[]),
            ("INSERT INTO role_assignments(user_id,group_id,role) VALUES (%s,%s,'READER')",[s.actor(self.reader),gid]),
            ("INSERT INTO role_assignments(user_id,department_id,document_id,role) VALUES (%s,%s,%s,'READER')",[s.actor(self.reader),self.dep,s.get_version(self.author,self.vid)[1]['document_id']])]:
            with self.assertRaises(DatabaseError),transaction.atomic():
                s.query(sql,params)

    def test_group_membership_can_register_a_user_without_direct_role(self):
        import io
        from django.core.management import call_command
        user = get_user_model().objects.create_user('nurgruppe',password='TestPassword-2026!')
        call_command('manage_group','create','Nur-Gruppe',reason='Neue Gruppe',stdout=io.StringIO())
        call_command('manage_group','add-member','Nur-Gruppe',user='nurgruppe',reason='Erstzuordnung',stdout=io.StringIO())
        uid = s.actor(user)
        self.assertEqual(s.query('SELECT * FROM role_assignments WHERE user_id=%s',[uid]),[])
        call_command('manage_group','grant','Nur-Gruppe',role='READER',document='IT-001',reason='Nur dieses Dokument',stdout=io.StringIO())
        self.publish()
        self.assertEqual(len(s.visible_versions(user)),1)

    def publish_successor(self,effective_from=None):
        vid = s.new_revision(self.author,self.vid,kind='minor',reason='Neue Fassung')
        s.edit_draft(self.author,vid,dict(title='Nachfolger',change_summary='Überarbeitet',effective_from=effective_from or timezone.now()-timedelta(hours=1),next_review_on=timezone.localdate()+timedelta(days=365)))
        s.transition(self.author,vid,'submit','Prüfen')
        s.transition(self.reviewer,vid,'accept','Geprüft')
        s.transition(self.reviewer,vid,'accept','Freigegeben')
        return vid

    def test_archiving_current_release_does_not_revive_previous(self):
        self.publish()
        successor = self.publish_successor()
        s.lifecycle_action(self.reviewer,successor,'archive','Fassung nicht mehr gültig',True)
        self.assertEqual(s.visible_versions(self.reader),[])
        self.assertIsNone(s.query('SELECT current_release(document_id) AS id FROM document_versions WHERE id=%s',[self.vid])[0]['id'])
        self.assertEqual(s.get_version(self.reviewer,successor)[1]['status'],'ARCHIVED')
        file_id = s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        with self.assertRaises(PermissionDenied):
            storage.download(self.reader,self.vid,file_id)
        self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='ARCHIVE'"))

    def test_archiving_old_release_keeps_current_release(self):
        self.publish()
        successor = self.publish_successor()
        s.lifecycle_action(self.reviewer,self.vid,'archive','Durch Nachfolger ersetzt',True)
        self.assertEqual([v['id'] for v in s.visible_versions(self.reader)],[successor])

    def test_document_withdrawal_blocks_reader_and_requires_new_approval(self):
        self.publish()
        s.lifecycle_action(self.reviewer,self.vid,'withdraw','Richtlinie wird zurückgezogen',True)
        self.assertEqual(s.visible_versions(self.reader),[])
        self.assertTrue(s.visible_versions(self.author)[0]['document_withdrawn'])
        with self.assertRaises(ValidationError):
            s.lifecycle_action(self.reviewer,self.vid,'withdraw','Doppelt',True)
        successor = self.publish_successor()
        self.assertEqual([v['id'] for v in s.visible_versions(self.reader)],[successor])
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM document_withdrawals')

    def test_withdrawal_covers_preapproved_future_versions(self):
        self.publish()
        future = self.publish_successor(timezone.now()+timedelta(days=7))
        s.lifecycle_action(self.reviewer,self.vid,'withdraw','Alle bisherigen Freigaben zurückziehen',True)
        self.assertEqual(s.visible_versions(self.reader),[])
        self.assertTrue(s.get_version(self.reviewer,future))
        self.assertEqual(len(s.query('SELECT * FROM document_withdrawals')),1)
        self.assertEqual(len(s.query("SELECT * FROM document_versions WHERE status='APPROVED'")),2)

    def test_lifecycle_permissions_confirmation_and_post(self):
        self.publish()
        for user in [self.author,self.approver,self.reader,self.outsider]:
            with self.assertRaises(PermissionDenied):
                s.lifecycle_action(user,self.vid,'withdraw','Test',True)
        with self.assertRaises(ValidationError):
            s.lifecycle_action(self.reviewer,self.vid,'withdraw','Test',False)
        self.client.force_login(self.approver)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/lifecycle/').status_code,405)
        self.assertEqual(s.query('SELECT * FROM document_withdrawals'),[])

    def test_archived_source_can_only_be_restored_by_new_revision(self):
        self.publish()
        s.lifecycle_action(self.reviewer,self.vid,'archive','Nicht mehr gültig',True)
        vid = s.new_revision(self.author,self.vid,kind='major',reason='Neuauflage')
        self.assertEqual(s.get_version(self.author,vid)[1]['status'],'DRAFT')
        self.assertEqual(s.visible_versions(self.reader),[])
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query("UPDATE document_versions SET status='APPROVED' WHERE id=%s",[self.vid])

    def test_workflow_tasks_follow_stage_and_group_revocation(self):
        self.assertEqual(s.workflow_tasks(self.reviewer),[])
        s.transition(self.author,self.vid,'submit','Prüfen')
        self.assertEqual([t['id'] for t in s.workflow_tasks(self.reviewer)],[self.vid])
        self.assertEqual(s.workflow_tasks(self.author),[])
        self.assertEqual(s.workflow_tasks(self.approver),[])
        s.transition(self.reviewer,self.vid,'accept','Geprüft')
        self.assertEqual([t['id'] for t in s.workflow_tasks(self.reviewer)],[self.vid])
        self.assertEqual(s.workflow_tasks(self.approver),[])
        self.assertEqual(s.workflow_tasks(self.outsider),[])
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get('/tasks/'),'IT-001')
        s.transition(self.reviewer,self.vid,'accept','Freigabe')
        self.assertEqual(s.workflow_tasks(self.approver),[])

    def test_task_list_does_not_expose_inaccessible_confidential_documents(self):
        s.edit_draft(self.author,self.vid,dict(title='Vertrauliche Prüfung',change_summary='Klassifiziert',effective_from=timezone.now(),next_review_on=timezone.localdate(),classification='CONFIDENTIAL'))
        s.transition(self.author,self.vid,'submit','Prüfen')
        self.assertEqual(s.workflow_tasks(self.approver),[])
        self.client.force_login(self.approver)
        self.assertNotContains(self.client.get('/tasks/',follow=True),'Vertrauliche Prüfung')

    def test_lifecycle_with_restricted_database_role(self):
        self.enable_runtime_role()
        self.publish()
        s.lifecycle_action(self.reviewer,self.vid,'withdraw','Rückzug',True)
        self.assertEqual(s.visible_versions(self.reader),[])
        s.lifecycle_action(self.reviewer,self.vid,'archive','Archivierung',True)
        self.assertEqual(s.get_version(self.reviewer,self.vid)[1]['status'],'ARCHIVED')
