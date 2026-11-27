from django.test import TestCase
from django.core.exceptions import PermissionDenied
from . import tests as fixtures, services as s, processes


class ProcessTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def data(self,title):
        return dict(title=title,description='Beschreibung '+title,owner_id=s.actor(self.author),inputs='',outputs='',responsibilities='',documents=[],references=[])

    def test_four_levels_drilldown_and_private_drafts(self):
        self.enable_runtime_role()
        parent=None;ids=[]
        for level in range(1,5):
            parent=processes.save(self.reviewer,None,parent,'P-'+str(level),self.data('Ebene '+str(level)),True,True,'')
            ids.append(parent)
        self.client.force_login(self.reader)
        for index,target in enumerate(ids):
            page=self.client.get(f'/processes/{target}/')
            self.assertEqual(page.status_code,200)
            self.assertEqual(len(page.context['crumbs']),index+1)
            self.assertContains(page,'Ebene '+str(index+1))
            self.assertNotContains(page,'Prozess bearbeiten')
        self.client.logout()
        self.assertEqual(self.client.get(f'/processes/{parent}/').status_code,200)
        processes.save(self.reviewer,ids[0],None,'P-1',self.data('Unsichtbarer Entwurf'),False,True,'')
        self.assertNotContains(self.client.get('/processes/'),'Unsichtbarer Entwurf')
        self.assertContains(self.client.get('/processes/'),'Ebene 1')
        processes.save(self.reviewer,ids[0],None,'P-1',self.data('Ebene 1'),False,False,'')
        for target in ids:self.assertEqual(self.client.get(f'/processes/{target}/').status_code,404)
        self.assertEqual(len(s.query('SELECT * FROM ims_process_revisions')),4)

    def test_draft_is_not_public_and_only_qmb_can_write(self):
        target=processes.save(self.reviewer,None,None,'DRAFT',self.data('Geheim'),False,True,'')
        self.assertEqual(self.client.get(f'/processes/{target}/').status_code,404)
        for user in (self.author,self.reader,self.approver):
            with self.assertRaises(PermissionDenied):processes.save(user,None,None,'X',self.data('X'),True,True,'')
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(f'/processes/{target}/edit/').status_code,200)
        response=self.client.post('/processes/new/',dict(code='WEB',title='Webprozess',owner_id=s.actor(self.author),description='Beschreibung',active='on',action='publish'))
        self.assertEqual(response.status_code,302)

    def test_hierarchy_publication_order_and_revision_guards(self):
        from django.core.exceptions import ValidationError
        from django.db import DatabaseError, transaction
        root=processes.save(self.reviewer,None,None,'ROOT',self.data('Root'),False,True,'')
        with self.assertRaises(ValidationError):processes.save(self.reviewer,None,root,'CHILD',self.data('Child'),True,True,'')
        self.assertEqual(len(processes.nodes(True)),1)
        processes.save(self.reviewer,root,None,'ROOT',self.data('Root'),True,True,'')
        parent=root
        for level in range(2,5):parent=processes.save(self.reviewer,None,parent,'L'+str(level),self.data('Level'),True,True,'')
        with self.assertRaises(ValidationError):processes.save(self.reviewer,None,parent,'FIFTH',self.data('Invalid'),False,True,'')
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('UPDATE ims_process_revisions SET payload=%s::jsonb',['{}'])
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('UPDATE ims_processes SET parent_id=%s WHERE id=%s',[parent,root])
        processes.save(self.reviewer,root,None,'ROOT',self.data('Root'),False,False,'')
        with self.assertRaises(ValidationError):processes.save(self.reviewer,None,None,'root',self.data('Duplicate'),False,True,'')

    def test_linked_documents_keep_their_access_controls(self):
        fixtures.WorkflowTests.publish(self)
        document=s.get_version(self.author,self.vid)[1]['document_id']
        s.query('SELECT set_document_login_required(%s,%s,true,%s)',[s.actor(self.reviewer),document,''])
        data=self.data('Dokumentverknüpfung');data['documents']=[document]
        root=processes.save(self.reviewer,None,None,'LINKS',data,True,True,'')
        self.assertNotContains(self.client.get(f'/processes/{root}/'),'Testdokument')
        self.client.force_login(self.reader)
        self.assertContains(self.client.get(f'/processes/{root}/'),'Testdokument')
        self.assertContains(self.client.get('/processes/',{'q':'Dokumentverknüpfung'}),'LINKS')
