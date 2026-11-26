from django.test import TestCase
from . import tests as fixtures,services as s
from .document_links import document_url


class NumberOverviewTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_overview_lists_old_current_and_inactive_numbers_with_filters(self):
        doc=s.get_version(self.author,self.vid)[1]['document_id']
        s.query('SELECT rename_document(%s,%s,%s,%s)',[s.actor(self.reviewer),doc,'NEW-001',''])
        self.enable_runtime_role();self.client.force_login(self.reviewer)
        response=self.client.get('/management/numbers/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['counts']['n'],2)
        self.assertContains(response,'IT-001');self.assertContains(response,'NEW-001')
        self.assertEqual(self.client.get('/management/numbers/',{'usage':'former','q':'NEW-001'}).context['counts']['n'],1)
        self.assertEqual(self.client.get('/management/numbers/',{'type':'Arbeitsanweisung'}).context['counts']['n'],0)
        s.query('SELECT set_document_active(%s,%s,false)',[s.actor(self.reviewer),doc])
        self.assertEqual(self.client.get('/management/numbers/',{'active':'0'}).context['counts']['n'],2)
        self.assertEqual(self.client.get('/management/numbers/',{'active':'1'}).context['counts']['n'],0)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get('/management/numbers/').status_code,403)

    def test_qmb_can_deactivate_from_detail_and_reactivate_without_leaving_document(self):
        self.publish();self.enable_runtime_role();self.client.force_login(self.reviewer)
        doc=s.get_version(self.reviewer,self.vid)[1]['document_id'];link=document_url(doc)
        self.assertContains(self.client.get(f'/versions/{self.vid}/'),'Dokument deaktivieren')
        response=self.client.post(f'/documents/{doc}/active/',{'active':'0'})
        self.assertRedirects(response,f'/versions/{self.vid}/')
        self.assertContains(self.client.get(f'/versions/{self.vid}/'),'Dokument reaktivieren')
        self.client.logout();self.assertEqual(self.client.get(link).status_code,403)
        self.client.force_login(self.reviewer)
        self.assertRedirects(self.client.post(f'/documents/{doc}/active/',{'active':'1'}),f'/versions/{self.vid}/')
        self.client.logout();self.assertEqual(self.client.get(link,follow=True).status_code,200)
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(f'/documents/{doc}/active/',{'active':'0'}).status_code,403)

    def test_visibility_action_is_available_in_qmb_draft_editor(self):
        s.query("UPDATE users SET qmb_role='PRIMARY' WHERE auth_user_id=%s",[self.author.pk])
        self.client.force_login(self.author)
        self.assertContains(self.client.get(f'/versions/{self.vid}/edit/'),'Dokument deaktivieren')
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get('/management/numbers/').status_code,403)
