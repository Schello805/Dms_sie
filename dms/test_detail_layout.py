from django.test import TestCase
from . import tests as fixtures,services as s


class DetailLayoutTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish

    def test_draft_has_edit_action_files_and_submission_on_one_page(self):
        self.client.force_login(self.author)
        response=self.client.get(f'/versions/{self.vid}/')
        for text in ('Dokumentaktionen','Entwurf und Zuordnungen bearbeiten','Original / Quelldatei','test.txt','PDF-Vorschau einblenden','An QMB senden','Normzuordnungen','Änderungsprotokoll'):
            self.assertContains(response,text)
        self.assertContains(response,f'/versions/{self.vid}/edit/')
        self.assertNotContains(response,'Überarbeitung beginnen')
        self.assertNotContains(response,'Rückzug und Archivierung')

    def test_review_and_release_actions_remain_available_with_comment_validation(self):
        s.transition(self.author,self.vid,'submit','Prüfen')
        self.client.force_login(self.reviewer)
        response=self.client.get(f'/versions/{self.vid}/')
        self.assertContains(response,'QMB-Entscheidung')
        self.assertContains(response,'Dokument freigeben')
        self.assertNotContains(response,'Entwurf und Zuordnungen bearbeiten')
        response=self.client.post(f'/versions/{self.vid}/action/',{'action':'reject','comment':''})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Bemerkung')
        self.assertEqual(s.get_version(self.author,self.vid)[1]['status'],'IN_REVIEW')

    def test_release_shows_revision_and_public_link_but_no_draft_editing(self):
        self.publish();self.client.force_login(self.author)
        response=self.client.get(f'/versions/{self.vid}/')
        self.assertContains(response,'Aktuelle Lesefassung')
        self.assertContains(response,'Überarbeitung beginnen')
        self.assertNotContains(response,'Entwurf und Zuordnungen bearbeiten')
