from datetime import timedelta
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError,transaction
from django.test import TestCase
from django.utils import timezone
from . import tests as fixtures,services as s
from .simple_workflow import upload_document,decide,returned_tasks
from .role_management import save_roles
from .policies import add_months,is_qmb

class SimpleIMSWorkflowTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def upload(self,submit=False,number='SOP-NEW'):
        data = dict(number=number,title='Neue SOP',document_type='Arbeitsanweisung',department=self.dep,
            change_summary='Neue Arbeitsanweisung',effective_from=timezone.now()-timedelta(days=60))
        return upload_document(self.author,data,SimpleUploadedFile('sop.txt',b'Neue SOP ohne Betriebsinhalte.'),submit)

    def admin(self):
        user = get_user_model().objects.create_user('roles-admin',password='TestPassword-2026!')
        s.query("INSERT INTO users(auth_user_id,display_name,settings_admin) VALUES (%s,'IT-Admin',true)",[user.pk])
        return user

    def test_invalid_qmb_decision_preserves_comment_and_does_not_approve(self):
        vid = self.upload(True)
        self.client.force_login(self.reviewer)
        comment = '<Entscheidung>' + 'x'*4000
        response = self.client.post(f'/versions/{vid}/action/',{'action':'reject','comment':comment})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'&lt;Entscheidung&gt;')
        self.assertEqual(s.get_version(self.reviewer,vid)[1]['status'],'IN_REVIEW')
        response = self.client.post(f'/versions/{vid}/action/',{'action':'reject','comment':''})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Bei Ablehnung ist eine Bemerkung für den Autor erforderlich.')
        self.assertNotContains(response,'Vorgang verbindlich ausführen')
        self.assertEqual(s.get_version(self.reviewer,vid)[1]['status'],'IN_REVIEW')

    def test_revision_can_be_submitted_without_repairing_missing_effective_date(self):
        vid = self.upload(True)
        decide(self.reviewer,vid,True,'Freigeben')
        revision = s.new_revision(self.author,vid,reason='Inhalt ergänzen')
        self.assertIsNotNone(s.get_version(self.author,revision)[1]['effective_from'])
        s.transition(self.author,revision,'submit','Erneut prüfen')
        decide(self.reviewer,revision,True,'Geprüft und freigegeben')
        self.assertEqual(s.get_version(self.reader,revision)[1]['status'],'APPROVED')

    def test_explicit_public_metadata_is_not_exposed_to_guests(self):
        vid = self.upload()
        _,draft = s.get_version(self.author,vid)
        s.edit_draft(self.author,vid,dict(title='Nur ausgewählte Personen',change_summary='Zugriff begrenzen',
            effective_from=draft['effective_from'],classification='PUBLIC'))
        s.change_access(self.author,vid,'EXPLICIT',[s.actor(self.author)],[],'Ausdrückliche Zugriffsliste')
        s.transition(self.author,vid,'submit','QMB anfordern')
        decide(self.reviewer,vid,True,'Geeignet')
        response = self.client.get('/')
        self.assertNotContains(response,'Nur ausgewählte Personen')
        self.assertNotContains(response,'SOP-NEW')

    def test_qmb_author_draft_has_submission_controls_and_rejection_note(self):
        save_roles(self.admin(),s.actor(self.author),True,True,False,'Autor ist zusätzlich QMB')
        vid = self.upload()
        self.client.force_login(self.author)
        response = self.client.get(f'/versions/{vid}/')
        self.assertContains(response,'An QMB senden')
        self.assertNotContains(response,'Dokument freigeben')
        s.transition(self.author,vid,'submit','Prüfen')
        decide(self.reviewer,vid,False,'Bitte Verantwortlichkeiten ergänzen.')
        self.assertContains(self.client.get(f'/versions/{vid}/'),'Bitte Verantwortlichkeiten ergänzen.')
        self.assertContains(self.client.get(f'/versions/{vid}/edit/'),'Entwurf bearbeiten')

    def test_office_file_does_not_offer_broken_pdf_preview(self):
        from . import storage
        vid = self.upload()
        storage.upload(self.author,vid,SimpleUploadedFile('arbeitsanweisung.docx',b'Fixture only'))
        file_id = s.query("SELECT id FROM file_objects WHERE original_name='arbeitsanweisung.docx'")[0]['id']
        self.client.force_login(self.author)
        self.assertNotContains(self.client.get(f'/versions/{vid}/'),f'/files/{file_id}/viewer/')

    def test_logout_returns_to_document_overview(self):
        self.client.force_login(self.reader)
        response = self.client.post('/logout/')
        self.assertRedirects(response,'/')

    def test_lazy_table_pages_preserve_filters_and_permissions(self):
        for i in range(32):
            self.upload(number=f'LAZY-{i:03d}')
        self.client.force_login(self.author)
        response = self.client.get('/documents/',{'q':'LAZY-'})
        self.assertContains(response,'LAZY-000')
        self.assertNotContains(response,'LAZY-030')
        chunk = self.client.get('/documents/',{'q':'LAZY-','page':2,'fragment':1}).json()
        self.assertIn('LAZY-030',chunk['html'])
        self.assertIn('LAZY-031',chunk['html'])
        self.assertNotIn('LAZY-000',chunk['html'])
        self.assertIsNone(chunk['next_url'])
        first = self.client.get('/documents/',{'q':'LAZY-','fragment':1}).json()
        self.assertIn('q=LAZY-',first['next_url'])
        self.assertIn('page=2',first['next_url'])
        descending = self.client.get('/documents/',{'q':'LAZY-','sort':'number','direction':'desc','fragment':1}).json()
        self.assertLess(descending['html'].index('LAZY-031'),descending['html'].index('LAZY-030'))
        self.assertNotIn('LAZY-000',descending['html'])
        self.assertIn('sort=number',descending['next_url'])
        self.assertIn('direction=desc',descending['next_url'])
        tail = self.client.get('/documents/',{'q':'LAZY-','sort':'number','direction':'desc','page':2,'fragment':1}).json()
        self.assertIn('LAZY-000',tail['html'])
        self.assertNotIn('LAZY-031',tail['html'])
        invalid = self.client.get('/documents/',{'sort':'number; DROP TABLE documents','direction':'malformed'})
        self.assertEqual(invalid.status_code,200)
        for key in s.CATALOG_SORTS:
            self.assertEqual(self.client.get('/documents/',{'sort':key,'direction':'desc'}).status_code,200)
        self.client.force_login(self.reader)
        hidden = self.client.get('/documents/',{'q':'LAZY-','page':2,'fragment':1}).json()
        self.assertNotIn('LAZY-',hidden['html'])
        self.assertIsNone(hidden['next_url'])

    def test_anonymous_start_is_catalog_without_internal_documents(self):
        vid = self.upload(True)
        decide(self.reviewer,vid,True,'Geeignet')
        for path in ('/', '/documents/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'Dokumentenübersicht')
            self.assertContains(response,'Anmelden')
            self.assertNotContains(response,'SOP-NEW')
            self.assertNotContains(response,'Dokument hochladen')
        self.assertEqual(self.client.get('/new/').status_code,302)

    def test_reader_start_page_is_only_catalog_with_direct_read_and_download(self):
        vid = self.upload(True)
        decide(self.reviewer,vid,True,'Geeignet')
        self.client.force_login(self.reader)
        response = self.client.get('/')
        self.assertContains(response,'Dokumentenübersicht')
        self.assertContains(response,'Ansehen')
        self.assertContains(response,'Herunterladen')
        for text in ['Mein IMS-Portal','Neu und geändert','Meine Kenntnisnahmen','Dokument hochladen','Admin-Einstellungen','Aufgaben,']:
            self.assertNotContains(response,text)
        self.assertEqual(self.client.get('/tasks/').status_code,302)

    def test_upload_draft_submit_one_qmb_approval_and_validity_from_approval(self):
        vid = self.upload()
        _,draft = s.get_version(self.author,vid)
        self.assertEqual(draft['status'],'DRAFT')
        self.assertIsNotNone(draft['uploaded_at'])
        original_effective = draft['effective_from']
        s.transition(self.author,vid,'submit','QMB-Freigabe anfordern')
        self.assertIn(vid,[t['id'] for t in s.workflow_tasks(self.reviewer)])
        decide(self.reviewer,vid,True,'Fachlich korrekt')
        _,released = s.get_version(self.reader,vid)
        self.assertEqual(released['status'],'APPROVED')
        self.assertEqual(released['effective_from'],original_effective)
        self.assertEqual(released['uploaded_at'],draft['uploaded_at'])
        self.assertEqual(released['review_due_on'],add_months(timezone.localdate(),24))
        self.assertIsNotNone(released['approved_at'])
        self.assertEqual(len(s.query('SELECT * FROM approval_decisions WHERE version_id=%s',[vid])),2)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM release_validity WHERE version_id=%s',[vid])

    def test_rejection_creates_author_task_with_note_and_resubmission_replaces_task(self):
        vid = self.upload(True)
        with self.assertRaises(ValidationError):
            decide(self.reviewer,vid,False,'')
        decide(self.reviewer,vid,False,'Schritt 3 muss korrigiert werden.')
        self.assertEqual(returned_tasks(self.author)[0]['comment'],'Schritt 3 muss korrigiert werden.')
        self.assertEqual(returned_tasks(self.reader),[])
        self.client.force_login(self.author)
        self.assertContains(self.client.get('/tasks/'),'Schritt 3 muss korrigiert werden.')
        s.transition(self.author,vid,'submit','Korrektur umgesetzt')
        self.assertEqual(returned_tasks(self.author),[])
        decide(self.reviewer,vid,True,'Jetzt korrekt')
        self.assertEqual(s.get_version(self.reader,vid)[1]['status'],'APPROVED')

    def test_multiple_qmb_accounts_and_only_three_public_role_choices(self):
        admin = self.admin()
        self.enable_runtime_role()
        save_roles(admin,s.actor(self.approver),False,True,False,'Zusätzlichen QMB benennen')
        self.assertTrue(is_qmb(self.approver))
        self.assertTrue(is_qmb(self.reviewer))
        vid = self.upload(True)
        self.assertIn(vid,[row['id'] for row in s.workflow_tasks(self.approver)])
        decide(self.approver,vid,True,'Als zusätzlicher QMB freigegeben')
        self.client.force_login(admin)
        response = self.client.get('/settings/users/')
        self.assertContains(response,'Autor')
        self.assertContains(response,'QMB')
        self.assertContains(response,'Admin (IT)')
        self.assertNotContains(response,'QMB-Vertretung')
        with self.assertRaises(PermissionDenied):
            save_roles(self.reader,s.actor(self.reader),True,True,True,'Unberechtigt')
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query("INSERT INTO role_assignments(user_id,role) VALUES (%s,'ADMIN')",[s.actor(self.reader)])

    def test_upload_ui_and_bell_rejection_and_approval_in_real_http_views(self):
        self.client.force_login(self.author)
        response = self.client.post('/new/',{'number':'UI-SOP','title':'UI Test','document_type':'Arbeitsanweisung','department':self.dep,
            'effective_from':'','change_summary':'','classification':'INTERNAL','intent':'submit','file':SimpleUploadedFile('ui.txt',b'SOP Test')})
        self.assertEqual(response.status_code,302)
        vid = s.query("SELECT v.id FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE d.number='UI-SOP'")[0]['id']
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get('/'),'Aufgaben,')
        self.assertContains(self.client.get('/tasks/'),'UI-SOP')
        response = self.client.post(f'/versions/{vid}/action/',{'action':'reject','comment':'Titel konkretisieren'})
        self.assertEqual(response.status_code,302)
        self.client.force_login(self.author)
        self.assertContains(self.client.get('/tasks/'),'Titel konkretisieren')
        self.client.post(f'/versions/{vid}/action/',{'action':'submit','comment':'Konkretisiert'})
        self.client.force_login(self.reviewer)
        self.client.post(f'/versions/{vid}/action/',{'action':'approve','comment':''})
        self.assertEqual(s.get_version(self.reader,vid)[1]['status'],'APPROVED')

    def test_explicitly_expired_release_still_visible_but_withdrawal_hides_it(self):
        vid = self.upload()
        s.query('UPDATE document_versions SET valid_until=%s WHERE id=%s',[timezone.now()-timedelta(days=1),vid])
        s.transition(self.author,vid,'submit','Prüfen')
        decide(self.reviewer,vid,True,'Freigabe')
        self.client.force_login(self.reader)
        self.assertContains(self.client.get('/'),'SOP-NEW')
        s.record_review(self.reviewer,vid,'UNCHANGED','Auch nach Ablauf fachlich geeignet')
        self.assertEqual(s.get_version(self.reader,vid)[1]['review_due_on'],add_months(timezone.localdate(),24))
        s.lifecycle_action(self.reviewer,vid,'withdraw','Explizit zurückziehen',True)
        self.assertNotContains(self.client.get('/'),'SOP-NEW')

    def test_existing_review_cycle_can_be_approved_without_changing_frozen_metadata(self):
        s.transition(self.author,self.vid,'submit','Bestehende Anfrage vor Umstellung')
        before = s.fingerprint(s.get_version(self.author,self.vid)[1])
        decide(self.reviewer,self.vid,True,'Übernommene Anfrage geprüft')
        after = s.get_version(self.reader,self.vid)[1]
        self.assertEqual(s.fingerprint(after),before)
        self.assertEqual(after['review_due_on'],add_months(timezone.localdate(),24))

    def test_self_approval_and_it_document_workflow_remain_forbidden(self):
        vid = self.upload(True)
        admin = self.admin()
        for user in [self.author,self.reader,admin]:
            with self.assertRaises(PermissionDenied):
                decide(user,vid,True,'Unberechtigt')
