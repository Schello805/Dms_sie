import json
from datetime import timedelta
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import TestCase,override_settings
from django.db import DatabaseError,transaction
from django.utils import timezone
from . import tests as fixtures,services as s,accounts,health
from .worklist import tasks_for


class ImprovementTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def admin(self):
        user=get_user_model().objects.create_user('itadmin',password='TestPassword-2026!')
        uid=s.query("INSERT INTO users(auth_user_id,display_name) VALUES (%s,'IT Admin') RETURNING id",[user.pk])[0]['id']
        s.query("INSERT INTO role_assignments(user_id,role) VALUES (%s,'ADMIN')",[uid])
        return user

    def test_create_account_runtime_role_and_no_secret_in_audit(self):
        admin=self.admin();self.enable_runtime_role()
        password='Initial-only-Password-9a7b3c!'
        uid=accounts.create_account(admin,'new-reader','Neue Person','new@example.test',password,password,'Eintritt')
        created=get_user_model().objects.get(username='new-reader')
        self.assertTrue(created.check_password(password))
        self.assertFalse(created.is_staff);self.assertFalse(created.is_superuser)
        self.assertTrue(s.allowed(uid,None,'READER'));self.assertFalse(s.allowed(uid,None,'ADMIN'))
        events=s.query("SELECT reason,details FROM audit_events WHERE object_type='user' AND object_id=%s",[str(uid)])
        self.assertNotIn(password,str(events));self.assertNotIn(created.password,str(events))
        with self.assertRaises(PermissionDenied):
            accounts.create_account(self.author,'unauthorized','U','',password,password,'Test')

    def test_deactivation_revokes_sessions_and_blocks_self_and_last_qmb(self):
        admin=self.admin();self.client.force_login(self.reader)
        session_key=self.client.session.session_key
        accounts.set_active(admin,s.actor(self.reader),False,'Austritt')
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        with self.assertRaises(ValidationError): accounts.set_active(admin,s.actor(admin),False,'Selbst')
        with self.assertRaises(ValidationError): accounts.set_active(admin,s.actor(self.reviewer),False,'Letzter QMB')
        accounts.set_active(admin,s.query('SELECT id FROM users WHERE auth_user_id=%s',[self.reader.pk])[0]['id'],True,'Wiedereintritt')
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())

    def test_password_change_requires_old_password_and_reset_logs_no_secret(self):
        admin=self.admin();uid=s.actor(self.reader);new='New-local-Password-9a7b3c!'
        self.enable_runtime_role()
        with self.assertRaises(ValidationError): accounts.change_password(self.reader,uid,new,new,'Eigene Änderung',old_password='wrong')
        accounts.change_password(self.reader,uid,new,new,'Eigene Änderung',old_password='TestPassword-2026!')
        self.assertTrue(get_user_model().objects.get(pk=self.reader.pk).check_password(new))
        accounts.change_password(admin,uid,'Other-local-Password-9a7b3c!','Other-local-Password-9a7b3c!','IT Rücksetzung')
        with self.assertRaises(PermissionDenied): accounts.change_password(self.author,uid,new,new,'Nicht erlaubt')
        self.assertNotIn(new,str(s.query("SELECT details,reason FROM audit_events WHERE action='CHANGE_LOCAL_PASSWORD'")))

    def test_reader_can_change_own_password_through_ui_and_is_logged_out(self):
        self.client.force_login(self.reader)
        new='Ui-local-Password-9a7b3c!'
        response=self.client.post('/account/password/',{'old_password':'TestPassword-2026!','password1':new,'password2':new,'reason':'Eigene Änderung'})
        self.assertRedirects(response,'/login/')
        self.assertTrue(get_user_model().objects.get(pk=self.reader.pk).check_password(new))

    def test_admin_list_shows_cli_assigned_admin_and_accounts_are_searchable(self):
        admin=self.admin();self.client.force_login(admin)
        response=self.client.get('/settings/users/',{'q':'itadmin'})
        self.assertContains(response,'Benutzer anlegen');self.assertContains(response,'name="admin" checked')
        self.assertNotContains(response,'@outsider')
        self.client.force_login(self.author)
        self.assertEqual(self.client.get('/settings/users/new/').status_code,403)

    def test_upcoming_reviews_are_in_worklist_and_bell(self):
        s.query('UPDATE document_versions SET next_review_on=%s WHERE id=%s',[timezone.localdate()+timedelta(days=7),self.vid])
        self.publish()
        data=tasks_for(self.reviewer)
        self.assertEqual(len(data['due']),1);self.assertEqual(data['due'][0]['days_left'],7)
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get('/'),'Aufgaben, 1 offen')
        s.record_review(self.reviewer,self.vid,'UNCHANGED','Weiter geeignet')
        self.assertEqual(tasks_for(self.reviewer)['due'],[])

    def test_version_comparison_is_protected_and_identifies_metadata(self):
        self.publish()
        revision=s.new_revision(self.author,self.vid,reason='Titel ändern')
        draft=s.get_version(self.author,revision)[1]
        s.edit_draft(self.author,revision,dict(title='Neuer geprüfter Titel',change_summary='Titel präzisiert',effective_from=draft['effective_from'],classification='INTERNAL'))
        self.client.force_login(self.author)
        self.assertContains(self.client.get(f'/versions/{revision}/compare/'),'Neuer geprüfter Titel')
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(f'/versions/{revision}/compare/').status_code,403)

    @override_settings(DYNAMIC_HOSTS=True,ALLOWED_HOSTS=['*'],EXPLICIT_HOSTS=['localhost','dms.example.test'])
    def test_dynamic_hosts_accept_changed_ips_but_not_arbitrary_dns_names(self):
        for host in ('192.168.1.12','192.168.1.99','[fd00::123]','dms.example.test'):
            self.assertEqual(self.client.get('/',HTTP_HOST=host).status_code,200,host)
        self.assertEqual(self.client.get('/',HTTP_HOST='attacker.example.test').status_code,400)

    def test_health_detects_missing_failed_and_stale_workers(self):
        with tempfile.TemporaryDirectory() as directory,override_settings(HEALTH_DIR=Path(directory)),patch('dms.health.shutil.disk_usage',return_value=type('D',(),{'free':100*1024**3,'total':200*1024**3})()):
            self.assertGreater(health.status()['count'],0)
            health.heartbeat('index');health.heartbeat('backup')
            self.assertEqual(health.status()['count'],0)
            health.heartbeat('backup','error')
            self.assertTrue(any('Sicherung' in text for text in health.status()['notices']))
            (Path(directory)/'index.json').write_text(json.dumps({'time':0,'status':'ok'}))
            self.assertTrue(any('Volltextdienst' in text for text in health.status()['notices']))

    def test_last_qmb_cannot_lose_role_through_ui_or_database(self):
        from .role_management import save_roles
        admin=self.admin();target=s.actor(self.reviewer);actor=s.actor(admin)
        self.enable_runtime_role()
        with self.assertRaises(ValidationError):
            save_roles(admin,target,False,False,False,'Letzten QMB entfernen')
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('SELECT set_operational_roles(%s,%s,false,false,false,%s)',[actor,target,'Direkter Aufruf'])
        self.assertTrue(s.query('SELECT is_qmb(%s) AS qmb',[target])[0]['qmb'])
        save_roles(admin,s.actor(self.approver),False,True,False,'Vertretung benennen')
        save_roles(admin,target,False,False,False,'Aufgabe übergeben')
        self.assertFalse(s.query('SELECT is_qmb(%s) AS qmb',[target])[0]['qmb'])

    def test_document_scoped_author_sees_returned_tasks_without_upload_permission(self):
        s.transition(self.author,self.vid,'submit','Prüfung')
        s.transition(self.reviewer,self.vid,'return','Inhalt korrigieren')
        uid=s.actor(self.author)
        s.query("DELETE FROM role_assignments WHERE user_id=%s AND role='AUTHOR'",[uid])
        s.query("INSERT INTO role_assignments(user_id,role,document_id) VALUES (%s,'AUTHOR',%s)",[uid,s.query('SELECT document_id FROM document_versions WHERE id=%s',[self.vid])[0]['document_id']])
        self.client.force_login(self.author)
        result=self.client.get('/')
        self.assertContains(result,'Aufgaben, 1 offen')
        self.assertContains(result,'>Autor</span>',html=False)
        self.assertNotContains(result,'Dokument hochladen')
        self.assertContains(self.client.get('/tasks/'),'Inhalt korrigieren')
        self.assertEqual(self.client.get('/new/').status_code,403)
