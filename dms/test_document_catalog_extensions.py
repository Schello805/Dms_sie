from django.test import TestCase
from django.utils import timezone
from . import tests as fixtures, services as s, masterdata
from .forms import DocumentUploadForm


class DocumentCatalogExtensionTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_standard_types_are_sorted_and_selected_before_number(self):
        form=DocumentUploadForm(user=self.author)
        self.assertEqual(list(form.fields)[:2],['document_type','number'])
        labels=[label for value,label in form.fields['document_type'].choices if value]
        self.assertEqual(labels,['Arbeitsanweisungen','Handbücher','Normen','Prozessbeschreibungen','Richtlinien','Vorlagen'])
        self.assertIn('ohne Versionsstand',form.fields['number'].help_text)

    def test_qmb_can_manage_departments_and_types(self):
        self.enable_runtime_role()
        dep=masterdata.save(self.reviewer,'departments',None,{'name':'Service','code':'SERV','active':True})
        category=masterdata.save(self.reviewer,'categories',None,{'name':'Eigene Dokumentenart','review_interval_months':24,'storage_location_id':1,'active':True})
        for kind,target in [('departments',dep),('categories',category)]:
            data=masterdata.get(kind,target);data.update(name='Umbenannt '+kind,active=False)
            masterdata.save(self.reviewer,kind,target,data)
            self.assertFalse(masterdata.get(kind,target)['active'])
            data['active']=True;masterdata.save(self.reviewer,kind,target,data)
            self.assertTrue(masterdata.get(kind,target)['active'])

    def test_author_and_stable_link_follow_current_release_after_revision(self):
        self.publish();self.client.force_login(self.reader)
        document=s.get_version(self.author,self.vid)[1]['document_id']
        stable=f'/documents/{document}/current/'
        page=self.client.get('/documents/')
        self.assertContains(page,'<th>Dokumentlink</th>',html=True)
        self.assertContains(page,'author')
        self.assertContains(page,'href="'+stable+'"')
        self.assertTrue(self.client.get(stable).url.startswith(f'/versions/{self.vid}/'))
        revision=s.new_revision(self.author,self.vid,'minor','Neue Fassung')
        draft=s.get_version(self.author,revision)[1]
        s.edit_draft(self.author,revision,{'title':'Folgef_ASSUNG','change_summary':'Aktualisiert','effective_from':timezone.now()})
        s.transition(self.author,revision,'submit','Prüfen')
        s.transition(self.reviewer,revision,'accept','Geprüft')
        s.transition(self.reviewer,revision,'accept','Freigegeben')
        self.assertContains(self.client.get('/documents/'),'href="'+stable+'"')
        self.assertTrue(self.client.get(stable).url.startswith(f'/versions/{revision}/'))
        self.assertEqual(s.get_version(self.author,revision)[1]['number'],'IT-001')
        s.lifecycle_action(self.reviewer,revision,'withdraw','',True)
        self.assertEqual(self.client.get(stable).status_code,403)
