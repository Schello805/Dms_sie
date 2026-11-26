from django.test import TestCase
from django.db import DatabaseError,transaction
from . import tests as fixtures,services as s
from .document_links import document_url
from .forms import DocumentUploadForm
from django.core.files.uploadedfile import SimpleUploadedFile


class NumberChangeTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_required_unique_number_is_validated_without_silently_replacing_it(self):
        data={'number':'','document_type':'Arbeitsanweisung','title':'Test','department':self.dep,'classification':'INTERNAL','intent':'draft'}
        form=DocumentUploadForm(data,{'file':SimpleUploadedFile('test.txt',b'test')},user=self.author)
        self.assertFalse(form.is_valid());self.assertIn('number',form.errors)
        data['number']=' it-001 '
        form=DocumentUploadForm(data,{'file':SimpleUploadedFile('test.txt',b'test')},user=self.author)
        self.assertFalse(form.is_valid());self.assertIn('number',form.errors)

    def test_owner_and_qmb_can_rename_release_without_changing_link_or_fingerprint(self):
        self.publish()
        version=s.get_version(self.author,self.vid)[1];doc=version['document_id']
        link=document_url(doc);digest=s.fingerprint(version)
        self.enable_runtime_role()
        for user,number in [(self.author,'AA-NEW-20'),(self.reviewer,'AA-NEW-21')]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(f'/documents/{doc}/number/',{'number':number,'reason':''}).status_code,302)
            self.assertEqual(document_url(doc),link)
            current=s.get_version(self.author,self.vid)[1]
            self.assertEqual(current['number'],number)
            self.assertEqual(s.fingerprint(current),digest)
            self.assertEqual(current['status'],'APPROVED')
        self.assertEqual(len(s.query('SELECT 1 FROM document_number_registry WHERE document_id=%s',[doc])),3)
        self.assertEqual(len(s.query("SELECT 1 FROM audit_events WHERE action='RENAME_DOCUMENT' AND object_id=%s",[str(doc)])),2)
        self.client.logout();self.assertEqual(self.client.get(link,follow=True).status_code,200)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('INSERT INTO documents(number,document_type,owner_id,responsible_department_id) VALUES (%s,%s,%s,%s)',['it-001','Richtlinie',s.actor(self.author),self.dep])
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(f'/documents/{doc}/number/',{'number':'UNAUTHORIZED'}).status_code,403)
        with self.assertRaises(DatabaseError),transaction.atomic():s.query('SELECT rename_document(%s,%s,%s,%s)',[s.actor(self.reader),doc,'UNAUTHORIZED',''])

    def test_duplicate_rename_is_rejected_without_changing_document_or_link(self):
        from django.utils import timezone
        other=s.create_document(self.author,{'number':'OTHER-20','title':'Anderes Dokument','document_type':'Richtlinie','department':self.dep,'effective_from':timezone.now()})
        doc=s.get_version(self.author,self.vid)[1]['document_id'];link=document_url(doc)
        self.client.force_login(self.author)
        response=self.client.post(f'/documents/{doc}/number/',{'number':' other-20 ','reason':''})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'bereits vergeben')
        self.assertEqual(s.get_version(self.author,self.vid)[1]['number'],'IT-001')
        self.assertEqual(document_url(doc),link)
