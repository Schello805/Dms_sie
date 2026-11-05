from unittest.mock import patch
import io
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.management import call_command
from django.db import DatabaseError,transaction
from django.test import TestCase
from . import tests as fixtures,test_notifications as mail_fixtures
from . import services as s,policies,notifications as n

class QMBWorkflowTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    publish = fixtures.WorkflowTests.publish
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def person(self,name,profile='NONE',admin=False):
        user = get_user_model().objects.create_user(name,password='TestPassword-2026!')
        s.query('INSERT INTO users(display_name,auth_user_id,qmb_role,settings_admin) VALUES (%s,%s,%s,%s)',[name,user.pk,profile,admin])
        return user

    def test_only_qmb_role_can_use_the_new_single_decision_interface(self):
        from .simple_workflow import decide
        from .role_management import save_roles
        lead = self.person('qmb-lead')
        admin = self.person('roles-admin',admin=True)
        s.query('UPDATE users SET qmb_approval_lead=true WHERE auth_user_id=%s',[lead.pk])
        s.transition(self.author,self.vid,'submit','Prüfung')
        with self.assertRaises(PermissionDenied):
            decide(lead,self.vid,True,'Keine QMB-Rolle')
        save_roles(admin,s.actor(lead),False,True,False,'QMB benennen')
        decide(lead,self.vid,True,'Als QMB geprüft und freigegeben')
        self.assertEqual(s.get_version(self.reader,self.vid)[1]['status'],'APPROVED')

    def test_qmb_cannot_approve_own_document_or_after_revocation(self):
        from .simple_workflow import decide
        s.query("UPDATE users SET qmb_role='PRIMARY' WHERE auth_user_id=%s",[self.author.pk])
        s.transition(self.author,self.vid,'submit','Eigene Fassung')
        with self.assertRaises(PermissionDenied):
            decide(self.author,self.vid,True,'Selbstfreigabe')
        deputy = self.person('additional-qmb','PRIMARY')
        self.assertEqual(len(s.workflow_tasks(deputy)),1)
        s.query("UPDATE users SET qmb_role='NONE' WHERE auth_user_id=%s",[deputy.pk])
        self.assertEqual(s.workflow_tasks(deputy),[])
        with self.assertRaises(PermissionDenied):
            decide(deputy,self.vid,True,'Widerrufen')

    def test_it_can_assign_lead_without_making_them_qmb(self):
        admin = self.person('it-manager',admin=True)
        lead = self.person('designated-lead')
        policies.save_qmb_team(admin,s.actor(self.reviewer),None,'Leitung benennen',lead_id=s.actor(lead))
        self.assertTrue(s.query('SELECT is_qmb_approval_lead(%s) AS yes',[s.actor(lead)])[0]['yes'])
        self.assertFalse(policies.is_qmb(lead))
        self.enable_runtime_role()
        policies.save_qmb_team(admin,s.actor(self.reviewer),None,'Leitung bestätigen',lead_id=s.actor(lead))

    def test_same_qmb_reviews_and_approves_with_qualification_snapshot(self):
        self.publish()
        decisions = s.query('SELECT actor_id,qmb_role_at_decision FROM approval_decisions ORDER BY id')
        self.assertEqual([r['actor_id'] for r in decisions],[s.actor(self.reviewer)]*2)
        self.assertEqual([r['qmb_role_at_decision'] for r in decisions],['PRIMARY','PRIMARY'])

    def test_department_reviewer_and_it_admin_cannot_replace_qmb(self):
        admin = self.person('it-admin',admin=True)
        s.transition(self.author,self.vid,'submit','QMB-Prüfung')
        for user in (self.approver,admin,self.author,self.reader):
            with self.assertRaises(PermissionDenied):
                s.transition(user,self.vid,'accept','Keine QMB-Qualifikation')
        self.assertEqual(s.query('SELECT * FROM approval_decisions'),[])

    def test_other_qmb_must_take_over_and_review_again_before_approval(self):
        deputy = self.person('qmb-deputy','DEPUTY')
        s.transition(self.author,self.vid,'submit','Prüfen')
        s.transition(self.reviewer,self.vid,'accept','QMB-Prüfung abgeschlossen')
        with self.assertRaises(PermissionDenied):
            s.transition(deputy,self.vid,'accept','Ohne eigene Prüfung')
        s.takeover_review(deputy,self.vid,'Vertretung wegen Abwesenheit')
        self.assertEqual(s.get_version(deputy,self.vid)[1]['status'],'IN_REVIEW')
        s.transition(deputy,self.vid,'accept','Erneut vollständig geprüft')
        s.transition(deputy,self.vid,'accept','Auf Basis eigener Prüfung freigegeben')
        self.assertEqual(s.get_version(deputy,self.vid)[1]['status'],'APPROVED')
        self.assertEqual(len(s.query('SELECT * FROM approval_decisions')),3)
        self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='QMB_TAKEOVER'"))

    def test_legacy_review_requires_fresh_qmb_cycle(self):
        s.transition(self.author,self.vid,'submit','Prüfen')
        s.transition(self.reviewer,self.vid,'accept','Vor Migration geprüft')
        # Simulate an immutable pre-migration review without a qualification snapshot.
        from unittest.mock import patch
        original = s.query
        def legacy_query(sql,params=None):
            rows = original(sql,params)
            if sql.startswith('SELECT actor_id,qmb_role_at_decision FROM approval_decisions'):
                rows[0]['qmb_role_at_decision'] = None
            return rows
        with patch.object(s,'query',side_effect=legacy_query),self.assertRaises(ValidationError):
            s.transition(self.reviewer,self.vid,'accept','Altzyklus freigeben')
        s.takeover_review(self.reviewer,self.vid,'Neue qualifizierte Prüfung')
        s.transition(self.reviewer,self.vid,'accept','Neu geprüft')
        s.transition(self.reviewer,self.vid,'accept','Freigegeben')

    def test_qmb_may_not_approve_own_document(self):
        s.query("UPDATE users SET qmb_role='DEPUTY' WHERE auth_user_id=%s",[self.author.pk])
        s.transition(self.author,self.vid,'submit','Eigene Fassung einreichen')
        with self.assertRaises(PermissionDenied):
            s.transition(self.author,self.vid,'accept','Selbstprüfung')
        s.transition(self.reviewer,self.vid,'accept','Unabhängig geprüft')
        s.transition(self.reviewer,self.vid,'accept','Freigegeben')

    def test_db_rejects_fabricated_qmb_claim_by_department_reviewer(self):
        s.transition(self.author,self.vid,'submit','Prüfen')
        w = s.query('SELECT * FROM workflow_instances')[0]
        with self.assertRaises(DatabaseError),transaction.atomic():
            for stage in ['REVIEW','APPROVAL']:
                s.query("INSERT INTO approval_decisions(version_id,actor_id,stage,decision,content_fingerprint,workflow_id,qmb_role_at_decision) VALUES (%s,%s,%s,'ACCEPT',%s,%s,'PRIMARY')",[self.vid,s.actor(self.approver),stage,w['content_fingerprint'],w['id']])
            s.query("UPDATE document_versions SET status='PENDING_APPROVAL' WHERE id=%s",[self.vid])
            s.query("UPDATE document_versions SET status='APPROVED' WHERE id=%s",[self.vid])

    def test_confidential_qmb_access_does_not_extend_to_department_reviewer(self):
        deputy = self.person('qualified-deputy','DEPUTY')
        s.query("UPDATE document_versions SET classification='CONFIDENTIAL' WHERE id=%s",[self.vid])
        for user in (self.reviewer,deputy):
            self.assertEqual(s.get_version(user,self.vid)[1]['id'],self.vid)
        for user in (self.approver,self.reader,self.outsider):
            with self.assertRaises(PermissionDenied):
                s.get_version(user,self.vid)

    def test_it_and_qmb_management_are_separated(self):
        admin = self.person('system-admin',admin=True)
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/settings/').status_code,200)
        self.assertEqual(self.client.get('/settings/email/').status_code,200)
        self.assertEqual(self.client.get('/management/').status_code,403)
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get('/management/'),'Aufbewahrungsort')
        self.assertEqual(self.client.get('/settings/email/').status_code,403)
        self.assertEqual(self.client.get('/settings/').status_code,403)
        self.assertEqual(self.client.get('/management/reminders/').status_code,200)

    def test_qmb_manages_logical_locations_and_retention_without_deleting_files(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.post('/management/locations/',{'name':'Papierarchiv','description':'Standort A','reason':'Fachliche Ablage ergänzen'}).status_code,302)
        place = s.query("SELECT id FROM storage_locations WHERE name='Papierarchiv'")[0]['id']
        data = {'reason':'Aufbewahrungsregeln festlegen'}
        for category in s.query('SELECT * FROM document_categories'):
            data[f"category_{category['id']}"] = 24
            data[f"retention_{category['id']}"] = 120
            data[f"location_{category['id']}"] = place
        self.assertEqual(self.client.post('/management/',data).status_code,302)
        self.assertEqual(s.query("SELECT retention_months FROM document_categories WHERE name='Richtlinie'")[0]['retention_months'],120)
        self.assertEqual(len(s.query('SELECT * FROM file_objects')),1)

    def test_provisioned_reader_is_basic_role_but_cannot_read_drafts(self):
        with patch('getpass.getpass',side_effect=['Unique-Reader-Password-2026!']*2):
            call_command('create_dms_user','new-reader',stdout=io.StringIO())
        user = get_user_model().objects.get(username='new-reader')
        with self.assertRaises(PermissionDenied):
            s.get_version(user,self.vid)
        self.publish()
        self.assertEqual(s.get_version(user,self.vid)[1]['id'],self.vid)
        self.assertFalse(s.allowed(s.actor(user),self.dep,'AUTHOR'))

    def test_it_cannot_change_qmb_reminder_policy_and_qmb_cannot_change_smtp(self):
        admin = self.person('tech-admin',admin=True)
        with self.assertRaises(PermissionDenied):
            n.save_notification_policy(admin,False,7,'Nicht fachlich berechtigt')
        with self.assertRaises(PermissionDenied):
            n.save_config(self.reviewer,{})
        n.save_notification_policy(self.reviewer,False,7,'Vorlauf fachlich festlegen')
        self.assertEqual(n.load_config()['reminder_days'],7)

class QMBNotificationTests(TestCase):
    setUp = mail_fixtures.NotificationTests.setUp
    publish = fixtures.WorkflowTests.publish
    configure = mail_fixtures.NotificationTests.configure
    dispatch_pending = mail_fixtures.NotificationTests.dispatch_pending

    def team(self):
        n.set_contact_email(self.admin,s.actor(self.reviewer),'qmb@example.test','QMB-Adresse')
        user = get_user_model().objects.create_user('deputy-mail',password='TestPassword-2026!',email='deputy@example.test')
        s.query("INSERT INTO users(display_name,auth_user_id,email,qmb_role) VALUES ('QMB-Vertretung',%s,'deputy@example.test','DEPUTY')",[user.pk])
        return user

    def test_author_and_both_qmbs_receive_exactly_one_email_each(self):
        self.team()
        self.assertEqual(n.queue_due(self.today),3)
        self.dispatch_pending(self.today)
        recipients = {item[0][0].split('<')[1].split('>')[0] for item in self.server.messages}
        self.assertEqual(recipients,{'author@example.test','qmb@example.test','deputy@example.test'})
        self.assertEqual(n.queue_due(self.today),0)
        self.assertFalse(n.dispatch_one(self.today))
        self.assertEqual(len(self.server.messages),3)

    def test_author_who_is_also_qmb_gets_no_duplicate(self):
        n.set_contact_email(self.admin,s.actor(self.reviewer),'qmb@example.test','QMB-Adresse')
        s.query("UPDATE users SET qmb_role='DEPUTY' WHERE auth_user_id=%s",[self.author.pk])
        self.assertEqual(n.queue_due(self.today),2)
        self.dispatch_pending(self.today)
        self.assertEqual(len(self.server.messages),2)
        self.assertEqual(s.query('SELECT count(*) AS n FROM review_notifications WHERE recipient_id=%s',[s.actor(self.author)])[0]['n'],1)

    def test_revoked_deputy_receives_no_queued_qmb_message(self):
        deputy = self.team()
        n.queue_due(self.today)
        s.query("UPDATE users SET qmb_role='NONE' WHERE auth_user_id=%s",[deputy.pk])
        self.dispatch_pending(self.today)
        recipients = ' '.join(str(item[0]) for item in self.server.messages)
        self.assertNotIn('deputy@example.test',recipients)
        self.assertEqual(len(self.server.messages),2)
