from django.test import TestCase
from . import tests as fixtures,services as s


class HelpAndEditTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp

    def test_help_is_available_for_guests_and_all_roles_from_footer(self):
        for user in (None,self.reader,self.author,self.reviewer):
            if user:self.client.force_login(user)
            else:self.client.logout()
            response=self.client.get('/help/')
            self.assertEqual(response.status_code,200)
            for section in ('Für Autoren','Für QMB','Für IT-Admins','Dokumente lesen und finden','Häufige Fragen'):
                self.assertContains(response,section)
            self.assertContains(self.client.get('/'),'href="/help/"')
        self.assertEqual(self.client.post('/help/').status_code,405)

    def test_edit_shows_context_files_and_date_and_preserves_draft_on_save(self):
        self.client.force_login(self.author)
        response=self.client.get(f'/versions/{self.vid}/edit/')
        self.assertTemplateUsed(response,'dms/edit.html')
        for text in ('IT-001','test.txt','Dokumentnummer ändern','Dateien verwalten','Zum Freigabebereich','type="date"'):
            self.assertContains(response,text)
        v=s.get_version(self.author,self.vid)[1]
        from django.utils import timezone
        response=self.client.post(f'/versions/{self.vid}/edit/',{'title':'Bearbeiteter Titel','effective_from':timezone.localdate(v['effective_from']).isoformat(),'classification':'INTERNAL','change_summary':''})
        self.assertEqual(response.status_code,302)
        v=s.get_version(self.author,self.vid)[1]
        self.assertEqual(v['title'],'Bearbeiteter Titel');self.assertEqual(v['status'],'DRAFT')
        invalid=self.client.post(f'/versions/{self.vid}/edit/',{'title':'','effective_from':'bad-date'})
        self.assertEqual(invalid.status_code,200);self.assertContains(invalid,'Bitte prüfe die markierten Angaben')
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/edit/').status_code,403)
