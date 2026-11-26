from django.test import TestCase
from django.contrib.auth.models import AnonymousUser
from . import tests as fixtures,services as s
from .document_links import document_url


class PublicReadingTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_guests_read_search_preview_download_without_login_and_without_mutation_rights(self):
        s.edit_draft(self.author,self.vid,dict(title='Öffentlich lesbar',change_summary='',classification='CONFIDENTIAL',effective_from=s.get_version(self.author,self.vid)[1]['effective_from']))
        self.publish()
        self.enable_runtime_role()
        version=s.get_version(self.author,self.vid)[1]
        file=s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        for path in ['/', '/documents/?q=lesbar&fragment=1',document_url(version['document_id']),f'/versions/{self.vid}/',f'/versions/{self.vid}/files/{file}/viewer/',f'/versions/{self.vid}/files/{file}/preview/',f'/versions/{self.vid}/files/{file}/']:
            response=self.client.get(path,follow=True)
            self.assertEqual(response.status_code,200,path)
            self.assertNotIn('/login/',response.request['PATH_INFO'])
            if response.streaming:self.assertTrue(b''.join(response.streaming_content))
        self.assertEqual(self.client.post(f'/versions/{self.vid}/action/',{'action':'approve'}).status_code,302)
        self.assertEqual(self.client.get('/management/').status_code,302)
        self.assertEqual(s.visible_versions(AnonymousUser(),search='lesbar')[0]['id'],self.vid)

    def test_drafts_superseded_withdrawn_and_inactive_documents_remain_unavailable(self):
        file=s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        self.assertEqual(self.client.get(f'/versions/{self.vid}/files/{file}/').status_code,403)
        self.assertEqual(s.visible_versions(AnonymousUser()),[])
        self.publish()
        doc=s.get_version(self.author,self.vid)[1]['document_id']
        s.query('SELECT set_document_active(%s,%s,false)',[s.actor(self.reviewer),doc])
        self.assertEqual(s.visible_versions(AnonymousUser()),[])
        self.assertEqual(self.client.get(document_url(doc)).status_code,403)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/files/{file}/').status_code,403)

    def test_superseded_and_withdrawn_versions_are_not_public(self):
        self.publish()
        old_file=s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        revision=s.new_revision(self.author,self.vid,'minor','Überarbeitung')
        s.transition(self.author,revision,'submit','Prüfen')
        s.transition(self.reviewer,revision,'accept','Geprüft')
        s.transition(self.reviewer,revision,'accept','Freigegeben')
        self.assertEqual(self.client.get(f'/versions/{self.vid}/files/{old_file}/').status_code,403)
        self.assertEqual([v['id'] for v in s.visible_versions(AnonymousUser(),catalog_only=True)],[revision])
        s.lifecycle_action(self.reviewer,revision,'withdraw','Zurückziehen',True)
        self.assertEqual(s.visible_versions(AnonymousUser(),catalog_only=True),[])
