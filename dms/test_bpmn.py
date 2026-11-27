from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase
from . import tests as fixtures, services as s, processes, bpmn, process_demo


class BpmnTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def root(self,code='BPMN',publish=True):
        return processes.save(self.reviewer,None,None,code,dict(title='BPMN Prozess',description='Beschreibung',owner_id=s.actor(self.author)),publish,True,'')

    def test_draft_release_read_access_and_runtime_guards(self):
        self.enable_runtime_role()
        process=self.root()
        version=bpmn.save(self.reviewer,process,bpmn.EMPTY,0,False)
        self.assertEqual(version,1)
        self.assertNotContains(self.client.get(f'/processes/{process}/bpmn/'),'StartEvent_IMS')
        changed=bpmn.EMPTY.replace('name="Start"','name="Freigegebener Start"')
        self.assertEqual(bpmn.save(self.reviewer,process,changed,1,True),2)
        self.assertContains(self.client.get(f'/processes/{process}/bpmn/'),'Freigegebener Start')
        bpmn.save(self.reviewer,process,bpmn.EMPTY,2,False)
        self.assertContains(self.client.get(f'/processes/{process}/bpmn/'),'Freigegebener Start')
        self.client.force_login(self.reader)
        page=self.client.get(f'/processes/{process}/bpmn/?edit=1')
        self.assertContains(page,'viewer.js');self.assertNotContains(page,'modeler.js')
        self.assertEqual(self.client.post(f'/processes/{process}/bpmn/',{},content_type='application/json').status_code,403)
        for user in (self.reader,self.author,self.approver):
            with self.assertRaises(PermissionDenied):bpmn.save(user,process,bpmn.EMPTY,3,True)
        with self.assertRaises(ValidationError):bpmn.save(self.reviewer,process,bpmn.EMPTY,1,True)
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('DELETE FROM process_bpmn_revisions')
        with self.assertRaises(DatabaseError),transaction.atomic():s.query("UPDATE process_bpmn SET live_xml='bad'")
        self.assertEqual(len(s.query('SELECT * FROM process_bpmn_revisions')),1)

    def test_hidden_and_unpublished_processes(self):
        parent=self.root(publish=False)
        with self.assertRaises(ValidationError):bpmn.save(self.reviewer,parent,bpmn.EMPTY,0,True)
        self.assertFalse(s.query('SELECT * FROM process_bpmn'))
        bpmn.save(self.reviewer,parent,bpmn.EMPTY,0,False)
        self.assertEqual(self.client.get(f'/processes/{parent}/bpmn/').status_code,404)
        processes.save(self.reviewer,parent,None,'BPMN',dict(title='Parent',description='Ready',owner_id=s.actor(self.author)),True,True,'')
        bpmn.save(self.reviewer,parent,bpmn.EMPTY,1,True)
        processes.save(self.reviewer,parent,None,'BPMN',dict(title='Parent',description='Ready',owner_id=s.actor(self.author)),False,False,'')
        self.assertEqual(self.client.get(f'/processes/{parent}/bpmn/').status_code,404)
        with self.assertRaises(ValidationError):bpmn.save(self.reviewer,parent,bpmn.EMPTY,2,False)

    def test_safe_xml_and_form_errors(self):
        for xml in ['<bad/>','<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',bpmn.EMPTY.replace('<bpmn:startEvent','<bpmn:scriptTask').replace('/></bpmn:process>','><bpmn:script>alert(1)</bpmn:script></bpmn:scriptTask></bpmn:process>'),bpmn.EMPTY.replace('name="Start"','name="Start" onload="alert(1)"'),'x'*(bpmn.MAX_BYTES+1)]:
            with self.assertRaises(ValidationError):bpmn.validate_xml(xml)
        self.assertEqual(bpmn.validate_xml(bpmn.EMPTY),bpmn.EMPTY)
        process=self.root();self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(f'/processes/{process}/bpmn/?edit=1').status_code,200)
        self.assertEqual(self.client.post(f'/processes/{process}/bpmn/',{'xml':bpmn.EMPTY,'expected':0,'publish':True},content_type='application/json').status_code,200)
        self.assertEqual(self.client.post(f'/processes/{process}/bpmn/',{'xml':bpmn.EMPTY,'expected':0,'publish':True},content_type='application/json').status_code,409)
        self.assertEqual(self.client.post(f'/processes/{process}/bpmn/',[],content_type='application/json').status_code,409)
        self.assertEqual(self.client.get('/assets/bpmn/18.31.0/modeler.js').status_code,200)
        self.assertEqual(self.client.get('/assets/bpmn/18.31.0/missing.js').status_code,404)
