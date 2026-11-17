from django.test import TestCase
from django.db import DatabaseError,transaction
from django.utils import timezone
from . import tests as fixtures,services as s,masterdata
from .document_links import document_url


class ReadableLinkTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_readable_link_is_frozen_after_category_rename_and_keeps_access_checks(self):
        document=s.get_version(self.author,self.vid)[1]['document_id']
        url=document_url(document)
        self.assertEqual(url,'/d/richtlinien/it-001/')
        category=s.query("SELECT id FROM document_categories WHERE name='Richtlinie'")[0]['id']
        data=masterdata.get('categories',category);data['name']='Umbenannte Richtlinien'
        masterdata.save(self.reviewer,'categories',category,data)
        self.assertEqual(document_url(document),url)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(url).status_code,403)
        self.publish()
        self.assertEqual(self.client.get(url).status_code,302)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code,302)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query("UPDATE document_links SET number_slug='changed' WHERE document_id=%s",[document])

    def test_normalization_collision_allocates_unique_frozen_paths(self):
        data={'document_type':'Arbeitsanweisung','department':self.dep,'title':'Datei','change_summary':'','effective_from':timezone.now()}
        paths=[]
        for number in ('AA/001','AA 001','Änderung ß'):
            vid=s.create_document(self.author,dict(data,number=number))
            paths.append(document_url(s.get_version(self.author,vid)[1]['document_id']))
        self.assertEqual(len(set(paths)),3)
        self.assertTrue(paths[0].startswith('/d/arbeitsanweisungen/aa-001/'))
        self.assertIn('aenderung-ss',paths[-1])
        self.enable_runtime_role()
        self.assertEqual(document_url(s.get_version(self.author,vid)[1]['document_id']),paths[-1])

    def test_upload_layout_groups_identity_file_and_optional_fields(self):
        self.client.force_login(self.author)
        response=self.client.get('/new/')
        self.assertContains(response,'1 · Dokument zuordnen')
        self.assertContains(response,'2 · Datei und Zuständigkeit')
        self.assertContains(response,'Weitere Angaben und Zuordnungen')
        html=response.content.decode()
        self.assertLess(html.index('name="document_type"'),html.index('name="number"'))
        self.assertLess(html.index('name="file"'),html.index('name="title"'))
        self.assertContains(response,'Als Entwurf speichern')
        from .forms import DocumentUploadForm,EditForm
        self.assertIn('required-marker',str(DocumentUploadForm(user=self.author)['document_type'].label_tag()))
        self.assertIn('required-marker',str(EditForm()['title'].label_tag()))
        edit=self.client.get(f'/versions/{self.vid}/edit/').content.decode()
        self.assertLess(edit.index('name="effective_from"'),edit.index('<details class="upload-options"'))
