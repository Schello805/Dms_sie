from django.test import TestCase
from django.db import transaction,DatabaseError
from django.core.exceptions import ValidationError
from . import tests as fixtures,services as s
from .simple_workflow import decide


class WorkflowRecoveryTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_new_qmb_can_release_own_already_submitted_version(self):
        for reviewed in (False,True):
            with self.subTest(reviewed=reviewed),transaction.atomic():
                s.transition(self.author,self.vid,'submit','Bitte prüfen')
                if reviewed:s.transition(self.reviewer,self.vid,'accept','Geprüft')
                before=s.query('SELECT * FROM approval_decisions WHERE version_id=%s',[self.vid])
                s.query("UPDATE users SET qmb_role='PRIMARY' WHERE auth_user_id=%s",[self.author.pk])
                self.enable_runtime_role()
                self.client.force_login(self.author)
                self.assertEqual(self.client.get('/tasks/summary/').json()['pending_count'],1)
                self.assertContains(self.client.get('/documents/'),'Jetzt freigeben')
                self.assertContains(self.client.get(f'/versions/{self.vid}/'),'direkt freigeben')
                self.assertNotContains(self.client.get(f'/versions/{self.vid}/'),'data-require-comment')
                response=self.client.post(f'/versions/{self.vid}/action/',{'action':'approve','comment':'Eigene Fassung geprüft'})
                self.assertEqual(response.status_code,302)
                self.assertEqual(s.get_version(self.reader,self.vid)[1]['status'],'APPROVED')
                for old in before:self.assertEqual(s.query('SELECT * FROM approval_decisions WHERE id=%s',[old['id']])[0],old)
                self.assertFalse(s.query('SELECT 1 FROM workflow_instances WHERE version_id=%s AND closed_at IS NULL',[self.vid]))
                self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='QMB_SELF_RELEASE_RESTART' AND object_id=%s",[str(self.vid)]))
                self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='QMB_RELEASE_NOTE' AND reason='Eigene Fassung geprüft'"))
                transaction.set_rollback(True)

    def test_rejected_own_release_rolls_back_restart(self):
        s.transition(self.author,self.vid,'submit','Prüfen')
        s.query("UPDATE users SET qmb_role='PRIMARY' WHERE auth_user_id=%s",[self.author.pk])
        with self.assertRaises(ValidationError):decide(self.author,self.vid,False,'Eigene Ablehnung')
        self.assertEqual(s.get_version(self.author,self.vid)[1]['status'],'IN_REVIEW')
        self.assertEqual(len(s.query('SELECT 1 FROM workflow_instances WHERE version_id=%s AND closed_at IS NULL',[self.vid])),1)

    def test_failed_direct_release_keeps_existing_cycle(self):
        from unittest.mock import patch
        from .simple_workflow import release_own_qmb_document
        s.transition(self.author,self.vid,'submit','Prüfen')
        s.query("UPDATE users SET qmb_role='PRIMARY' WHERE auth_user_id=%s",[self.author.pk])
        original=s.query
        def fail_release(sql,params=None):
            if 'SELECT release_qmb_document' in sql:raise ValidationError('Simulierter Freigabefehler')
            return original(sql,params)
        with patch.object(s,'query',side_effect=fail_release),self.assertRaises(ValidationError):
            release_own_qmb_document(self.author,self.vid)
        self.assertEqual(s.get_version(self.author,self.vid)[1]['status'],'IN_REVIEW')
        self.assertEqual(len(s.query('SELECT 1 FROM workflow_instances WHERE version_id=%s AND closed_at IS NULL',[self.vid])),1)
        self.assertFalse(s.query("SELECT 1 FROM audit_events WHERE action='QMB_SELF_RELEASE_RESTART'"))
