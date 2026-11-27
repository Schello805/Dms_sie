from django.core.exceptions import PermissionDenied
from django.test import TestCase
from . import tests as fixtures, services as s, processes, process_demo, demo_diagrams, bpmn


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
        self.assertEqual(len(s.query('SELECT * FROM process_bpmn WHERE live_xml IS NOT NULL')),72)
        self.assertEqual(len(s.query('SELECT * FROM process_bpmn_revisions')),72)
        self.assertEqual(len(s.query('SELECT * FROM process_controls')),2)
        self.assertIn('Automaten fertigen und prüfen',self.client.get('/processes/').context['config']['xml'])
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

    def test_existing_diagrams_and_drafts_are_preserved_when_filling_gaps(self):
        self.enable_runtime_role()
        process_demo.install(self.reviewer)
        rows=s.query('SELECT * FROM ims_processes WHERE demo ORDER BY id')
        root=rows[0]
        version=s.query('SELECT edit_version FROM process_bpmn WHERE process_id=%s',[root['id']])[0]['edit_version']
        custom=bpmn.EMPTY.replace('name="Start"','name="Eigener Arbeitsstand"')
        bpmn.save(self.reviewer,root['id'],custom,version,False)
        self.assertEqual(demo_diagrams.ensure(self.reviewer),0)
        self.assertEqual(s.query('SELECT draft_xml FROM process_bpmn WHERE process_id=%s',[root['id']])[0]['draft_xml'],custom)
        # A real process must never receive an automatically generated diagram.
        real=processes.save(self.reviewer,None,None,'NON-DEMO',dict(title='Eigener Prozess',description='Real',owner_id=s.actor(self.author)),True,True,'')
        self.assertEqual(demo_diagrams.ensure(self.reviewer),0)
        self.assertFalse(s.query('SELECT 1 FROM process_bpmn WHERE process_id=%s',[real]))
        leaf=next(row for row in rows if row['level']==4)
        xml=s.query('SELECT live_xml FROM process_bpmn WHERE process_id=%s',[leaf['id']])[0]['live_xml']
        bpmn.validate_xml(xml)
        self.assertIn('exclusiveGateway',xml)
        self.assertIn('Flow_Retry',xml)
        self.assertIn('Abweichung klären',xml)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.post('/processes/demo/',{'action':'diagrams'}).status_code,302)
        self.assertEqual(len(s.query('SELECT * FROM process_bpmn')),72)

    def test_upgrade_fills_only_missing_models(self):
        from unittest.mock import patch
        with patch('dms.process_demo.demo_diagrams.ensure'):
            process_demo.install(self.reviewer)
        self.assertEqual(len(s.query('SELECT * FROM process_bpmn')),0)
        self.assertEqual(demo_diagrams.ensure(self.reviewer),72)
        self.assertEqual(demo_diagrams.ensure(self.reviewer),0)

    def test_demo_diagram_drilldown_and_hidden_urls(self):
        process_demo.install(self.reviewer)
        rows=s.query('SELECT * FROM ims_processes WHERE demo ORDER BY code')
        root=rows[0]
        page=self.client.get('/processes/')
        self.assertContains(page,f'/processes/{root["id"]}/')
        for level in range(1,5):
            node=next(row for row in rows if row['level']==level)
            response=self.client.get(f'/processes/{node["id"]}/bpmn/')
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.context['crumbs']),level)
            self.assertIn('Flow_',response.context['config']['xml'])
            if level<4:
                target=next(row for row in rows if row['parent_id']==node['id'])
                self.assertIn('IMS-PROCESS-ID:'+str(target['id']),response.context['config']['xml'])
        process_demo.toggle(self.reviewer,False)
        self.assertEqual(self.client.get(f'/processes/{root["id"]}/bpmn/').status_code,404)
