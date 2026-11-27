from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from . import services as s, storage, tests as fixtures


class CatalogTypeFilterTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    publish = fixtures.WorkflowTests.publish
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def published_instruction(self, number):
        vid = s.create_document(self.author, {
            'number': number, 'document_type': 'Arbeitsanweisung',
            'department': self.dep, 'title': 'Filterprüfung '+number,
            'effective_from': timezone.now(),
        })
        storage.upload(self.author, vid, SimpleUploadedFile('fixture.txt', b'Typfilter'))
        s.transition(self.author, vid, 'submit', 'Prüfen')
        s.transition(self.reviewer, vid, 'accept', 'Geprüft')
        s.transition(self.reviewer, vid, 'accept', 'Freigegeben')
        return vid

    def test_type_filter_replaces_status_for_every_role_without_exposing_drafts(self):
        published = self.published_instruction('AA-FILTER')
        self.enable_runtime_role()
        for user in (None, self.reader, self.author, self.reviewer):
            self.client.force_login(user) if user else self.client.logout()
            page = self.client.get('/documents/', {
                'document_type': 'Arbeitsanweisung', 'department': str(self.dep),
                'q': 'Filterprüfung', 'sort': 'department', 'status': 'DRAFT',
            })
            self.assertContains(page, 'id="document_type"')
            self.assertNotContains(page, 'id="status"')
            self.assertContains(page, 'AA-FILTER')
            self.assertNotContains(page, 'IT-001')
            self.assertContains(page, 'value="Arbeitsanweisung" selected')
            self.assertNotContains(page, 'status=')
            self.assertEqual([v['id'] for v in page.context['versions']], [published])
            labels = [t['label'] for t in page.context['document_types']]
            self.assertEqual(labels, sorted(labels, key=str.lower))
            page = self.client.get('/documents/', {'document_type': 'Richtlinie'})
            self.assertEqual([v['id'] for v in page.context['versions']], [self.vid] if user==self.author else [])
        self.assertEqual(s.visible_versions(AnonymousUser(), document_type="' OR 1=1 --", catalog_only=True), [])

    def test_type_filter_is_preserved_on_second_lazy_page_and_sorting_links(self):
        self.publish()
        ids = {self.published_instruction(f'AA-PAGE-{i:03}') for i in range(31)}
        query = {'document_type': 'Arbeitsanweisung', 'department': str(self.dep),
                 'sort': 'number', 'direction': 'desc', 'status': 'APPROVED'}
        page = self.client.get('/documents/', query)
        for header in page.context['sort_headers']:
            self.assertIn('document_type=Arbeitsanweisung', header['url'])
            self.assertIn('department='+str(self.dep), header['url'])
            self.assertNotIn('status=', header['url'])
        first = self.client.get('/documents/', {**query, 'fragment': '1'}).json()
        self.assertEqual(first['total_count'], 31)
        self.assertEqual(first['html'].count('<tr>'), 30)
        self.assertIn('document_type=Arbeitsanweisung', first['next_url'])
        self.assertNotIn('status=', first['next_url'])
        second = self.client.get(first['next_url']+'&fragment=1').json()
        self.assertEqual(second['html'].count('<tr>'), 1)
        self.assertIn('AA-PAGE-000', second['html'])
        self.assertNotIn('IT-001', first['html']+second['html'])
        self.assertIsNone(second['next_url'])
        self.assertEqual({v['id'] for v in s.visible_versions(AnonymousUser(),document_type='Arbeitsanweisung',catalog_only=True)}, ids)
