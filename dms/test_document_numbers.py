from django.test import TestCase
from django.db import DatabaseError, transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from . import tests as fixtures,services as s,masterdata


class DocumentNumberTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def create(self,kind='Arbeitsanweisung',number=None,user=None):
        return s.create_document(user or self.author,dict(number=number,document_type=kind,department=self.dep,title='Automatische Nummer',change_summary='',effective_from=timezone.now()))

    def test_auto_numbers_share_sequence_and_prefix_change_keeps_issued_numbers(self):
        self.enable_runtime_role()
        first=s.get_version(self.author,self.create())[1]
        second=s.get_version(self.author,self.create('Prozess'))[1]
        self.assertRegex(first['number'],r'^AA-[0-9]{4,}$')
        self.assertRegex(second['number'],r'^PB-[0-9]{4,}$')
        self.assertGreater(int(second['number'].split('-')[1]),int(first['number'].split('-')[1]))
        category=s.query("SELECT id FROM document_categories WHERE name='Arbeitsanweisung'")[0]['id']
        s.query('SELECT set_category_number_prefix(%s,%s,%s,%s)',[s.actor(self.reviewer),category,'sop',''])
        third=s.get_version(self.author,self.create())[1]
        self.assertTrue(third['number'].startswith('SOP-'))
        self.assertEqual(s.get_version(self.author,first['id'])[1]['number'],first['number'])
        self.assertEqual(len(s.query('SELECT 1 FROM document_number_registry WHERE document_id=%s',[first['document_id']])),1)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('SELECT set_category_number_prefix(%s,%s,%s,%s)',[s.actor(self.author),category,'EVIL',''])

    def test_deactivate_retains_number_hides_release_and_denies_reuse(self):
        fixtures.WorkflowTests.publish(self)
        doc=s.get_version(self.author,self.vid)[1]['document_id']
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get('/management/numbers/').status_code,200)
        self.assertEqual(self.client.get(f'/management/numbers/{doc}/active/').status_code,405)
        self.assertEqual(self.client.post(f'/management/numbers/{doc}/active/',{'active':'0'}).status_code,302)
        self.assertEqual(s.visible_versions(self.reader),[])
        with self.assertRaises(PermissionDenied):s.get_version(self.author,self.vid)
        self.assertFalse(s.get_version(self.reviewer,self.vid)[1]['document_active'])
        self.assertEqual(self.client.get(f'/documents/{doc}/current/').status_code,403)
        for number in ('IT-001',' it-001 '):
            with self.assertRaises(DatabaseError),transaction.atomic():self.create(number=number)
        self.enable_runtime_role()
        for sql,args in [('DELETE FROM document_number_registry WHERE document_id=%s',[doc]),('DELETE FROM documents WHERE id=%s',[doc]),("UPDATE documents SET number='NEW' WHERE id=%s",[doc])]:
            with self.assertRaises(DatabaseError),transaction.atomic():s.query(sql,args)
        s.query('SELECT set_document_active(%s,%s,true)',[s.actor(self.reviewer),doc])
        self.assertEqual(s.visible_versions(self.reader)[0]['number'],'IT-001')

    def test_summary_and_register_are_role_guarded_and_counts_follow_submission(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get('/tasks/summary/').status_code,403)
        self.assertEqual(self.client.get('/management/numbers/').status_code,403)
        doc=s.get_version(self.author,self.vid)[1]['document_id']
        self.assertEqual(self.client.post(f'/management/numbers/{doc}/active/',{'active':'0'}).status_code,403)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get('/tasks/summary/').json()['pending_count'],0)
        s.transition(self.author,self.vid,'submit','Bitte prüfen')
        response=self.client.get('/tasks/summary/')
        self.assertEqual(response.json()['pending_count'],1)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertNotIn('title',response.json())

    def test_existing_qmb_draft_has_discoverable_post_only_release(self):
        vid=self.create(user=self.reviewer)
        from .storage import upload
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload(self.reviewer,vid,SimpleUploadedFile('draft.txt',b'QMB draft'))
        self.client.force_login(self.reviewer)
        html=self.client.get('/documents/').content.decode()
        self.assertIn(f'/versions/{vid}/#document-workflow',html)
        self.assertIn('Jetzt freigeben',html)
        self.assertContains(self.client.get(f'/versions/{vid}/'),'Änderungen direkt freigeben')
        self.assertEqual(s.get_version(self.reviewer,vid)[1]['status'],'DRAFT')
        self.assertEqual(self.client.post(f'/versions/{vid}/action/',{'action':'submit','comment':''}).status_code,302)
        self.assertEqual(s.get_version(self.reader,vid)[1]['status'],'APPROVED')

    def test_upload_form_ignores_client_number_and_qmb_can_save_prefix(self):
        from .forms import DocumentUploadForm
        from django.core.files.uploadedfile import SimpleUploadedFile
        form=DocumentUploadForm({'document_type':'Arbeitsanweisung','number':'FORGED','title':'Automatisch','department':self.dep,'classification':'INTERNAL','intent':'draft'},
            {'file':SimpleUploadedFile('file.txt',b'Contents')},user=self.author)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.cleaned_data['number'],'')
        self.assertFalse(form.fields['number'].required)
        self.assertTrue(form.fields['number'].widget.attrs['readonly'])
        self.enable_runtime_role()
        category=s.query("SELECT id FROM document_categories WHERE name='Arbeitsanweisung'")[0]['id']
        data=masterdata.get('categories',category);data['number_prefix']='NEU'
        masterdata.save(self.reviewer,'categories',category,data)
        self.assertEqual(masterdata.get('categories',category)['number_prefix'],'NEU')
