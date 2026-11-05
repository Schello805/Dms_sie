from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from . import tests as fixtures,services as s

class CatalogVisibilityTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    publish = fixtures.WorkflowTests.publish
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def test_unreleased_rows_are_only_listed_for_the_version_author(self):
        for phase in ['DRAFT','IN_REVIEW','PENDING_APPROVAL']:
            self.assertEqual([v['id'] for v in s.visible_versions(self.author,catalog_only=True)],[self.vid])
            for user in [self.reviewer,self.approver,self.reader,self.outsider]:
                self.assertEqual(s.visible_versions(user,catalog_only=True),[],(phase,user.username))
            self.client.force_login(self.author)
            response = self.client.get('/documents/')
            self.assertContains(response,'Testdokument')
            self.assertContains(response,'<span class="badge">Entwurf</span>',html=True)
            self.assertNotContains(response,'In Prüfung')
            self.assertNotContains(response,'Zur Freigabe')
            if phase=='DRAFT':
                s.transition(self.author,self.vid,'submit','QMB-Prüfung')
            elif phase=='IN_REVIEW':
                self.assertEqual(len(s.workflow_tasks(self.reviewer)),1)
                s.transition(self.reviewer,self.vid,'accept','QMB-Prüfung abgeschlossen')
        self.assertEqual(len(s.workflow_tasks(self.reviewer)),1)
        self.client.force_login(self.reviewer)
        self.assertNotContains(self.client.get('/documents/'),'Testdokument')
        self.assertContains(self.client.get('/tasks/'),'Testdokument')
        self.assertEqual(self.client.get(f'/versions/{self.vid}/').status_code,200)

    def test_status_query_cannot_reintroduce_foreign_drafts(self):
        s.transition(self.author,self.vid,'submit','Prüfen')
        for status in ['', 'DRAFT','IN_REVIEW','PENDING_APPROVAL','ARCHIVED']:
            self.assertEqual(s.visible_versions(self.reviewer,status=status,catalog_only=True),[])
        self.assertEqual([v['id'] for v in s.visible_versions(self.author,status='DRAFT',catalog_only=True)],[self.vid])
        self.assertEqual(s.visible_versions(self.author,status='IN_REVIEW',catalog_only=True),[])

    def test_catalog_shows_only_current_release_and_own_revision(self):
        self.publish()
        for user in [self.author,self.reviewer,self.reader]:
            self.assertEqual([v['id'] for v in s.visible_versions(user,catalog_only=True)],[self.vid])
        self.client.force_login(self.reader)
        self.assertContains(self.client.get('/documents/'),'<span class="badge">Freigegeben</span>',html=True)
        revision = s.new_revision(self.author,self.vid,'minor','Überarbeitung')
        self.assertEqual({v['id'] for v in s.visible_versions(self.author,catalog_only=True)},{self.vid,revision})
        self.assertEqual([v['id'] for v in s.visible_versions(self.reviewer,catalog_only=True)],[self.vid])
        s.edit_draft(self.author,revision,dict(title='Neue Fassung',change_summary='Aktualisiert',effective_from=timezone.now()-timedelta(minutes=1),next_review_on=timezone.localdate()+timedelta(days=90)))
        s.transition(self.author,revision,'submit','Prüfen')
        s.transition(self.reviewer,revision,'accept','Prüfung')
        s.transition(self.reviewer,revision,'accept','Freigabe')
        self.assertEqual([v['id'] for v in s.visible_versions(self.author,catalog_only=True)],[revision])
        s.lifecycle_action(self.reviewer,revision,'withdraw','Zurückgezogen',True)
        self.assertEqual(s.visible_versions(self.author,catalog_only=True),[])

    def test_scoped_author_role_does_not_show_another_authors_draft(self):
        s.query("INSERT INTO role_assignments(user_id,role,department_id) VALUES (%s,'AUTHOR',%s)",[s.actor(self.approver),self.dep])
        self.assertEqual(s.visible_versions(self.approver,catalog_only=True),[])
        self.enable_runtime_role()
        self.assertEqual([v['id'] for v in s.visible_versions(self.author,catalog_only=True)],[self.vid])
        self.assertEqual(s.visible_versions(self.approver,catalog_only=True),[])
