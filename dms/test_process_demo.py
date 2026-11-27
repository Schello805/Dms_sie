from django.core.exceptions import PermissionDenied
from django.test import TestCase
from . import tests as fixtures, services as s, processes, process_demo


class ProcessDemoTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_demo_is_optional_idempotent_and_hides_whole_tree(self):
        self.enable_runtime_role()
        own=processes.save(self.reviewer,None,None,'REAL',dict(title='Eigener Prozess',description='Echter Inhalt',owner_id=s.actor(self.author)),True,True,'')
        self.assertFalse(process_demo.state()['installed'])
        process_demo.install(self.reviewer)
        rows=s.query('SELECT * FROM ims_processes WHERE demo')
        self.assertEqual(len(rows),72)
        self.assertEqual({row['level'] for row in rows},{1,2,3,4})
        self.assertEqual(len(s.query('SELECT * FROM process_controls')),2)
        self.assertContains(self.client.get('/processes/'),'Automaten fertigen und prüfen')
        leaf=next(row for row in rows if row['level']==4)
        self.assertContains(self.client.get(f'/processes/{leaf["id"]}/'),'DEMO')
        process_demo.install(self.reviewer)
        self.assertEqual(len(s.query('SELECT * FROM ims_processes WHERE demo')),72)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.post('/processes/demo/',{'action':'hide'}).status_code,302)
        self.assertNotContains(self.client.get('/processes/'),'Automaten fertigen und prüfen')
        self.client.logout()
        self.assertEqual(self.client.get(f'/processes/{leaf["id"]}/').status_code,404)
        self.assertEqual(self.client.get(f'/processes/{own}/').status_code,200)
        process_demo.toggle(self.reviewer,True)
        self.assertEqual(self.client.get(f'/processes/{leaf["id"]}/').status_code,200)
        self.assertEqual(len(s.query('SELECT * FROM ims_processes WHERE demo')),72)

    def test_only_qmb_can_install_or_toggle_and_post_required(self):
        for user in (self.reader,self.author,self.approver):
            with self.assertRaises(PermissionDenied):process_demo.install(user)
            with self.assertRaises(PermissionDenied):process_demo.toggle(user,True)
            self.client.force_login(user)
            self.assertEqual(self.client.post('/processes/demo/',{'action':'install'}).status_code,403)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get('/processes/demo/').status_code,405)
