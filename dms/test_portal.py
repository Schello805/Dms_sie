import io
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError,transaction
from django.test import TestCase,Client
from django.utils import timezone
from pypdf import PdfReader
from . import tests as fixtures
from . import services as s,portal,evidence,storage,previews

class EmployeePortalTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    publish = fixtures.WorkflowTests.publish
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def distribution(self,requires_ack=True,audiences=()):
        portal.save_distribution(self.author,self.vid,'SUBSTANTIAL',requires_ack,14,'Synonym Maschinenstart',list(audiences),'Zielgruppe festlegen')

    def admin(self):
        user = get_user_model().objects.create_user('it-admin',password='TestPassword-2026!')
        s.query("INSERT INTO users(auth_user_id,display_name,settings_admin) VALUES (%s,'IT-Admin',true)",[user.pk])
        return user

    def test_portal_only_current_release_and_stable_link_follows_successor(self):
        self.client.force_login(self.author)
        self.assertContains(self.client.get('/'),'Testdokument')
        self.client.force_login(self.reader)
        self.assertNotContains(self.client.get('/'),'Testdokument')
        self.client.force_login(self.author)
        self.publish()
        doc = s.get_version(self.author,self.vid)[1]['document_id']
        self.assertContains(self.client.get('/'),'Testdokument')
        self.assertContains(self.client.get(f'/documents/{doc}/current/'),'Version 1.0')
        second = s.new_revision(self.author,self.vid,'minor','Neue Lesefassung')
        s.edit_draft(self.author,second,dict(title='Überarbeitete Lesefassung',change_summary='Geändert',effective_from=timezone.now()-timedelta(minutes=1),next_review_on=timezone.localdate()+timedelta(days=100)))
        s.transition(self.author,second,'submit','Prüfen')
        s.transition(self.reviewer,second,'accept','Geprüft')
        s.transition(self.reviewer,second,'accept','Freigeben')
        response = self.client.get(f'/documents/{doc}/current/')
        self.assertContains(response,'Version 1.1')
        self.assertNotContains(response,'Version 1.0')
        s.lifecycle_action(self.reviewer,second,'withdraw','Sperren',True)
        self.assertEqual(self.client.get(f'/documents/{doc}/current/').status_code,403)

    def test_target_group_does_not_grant_access_to_confidential_document(self):
        group = s.query("INSERT INTO audience_groups(name) VALUES ('Maschinenführer') RETURNING id")[0]['id']
        uid = s.actor(self.reader)
        s.query('INSERT INTO audience_memberships VALUES (%s,%s)',[uid,group])
        self.distribution(audiences=[group])
        s.query("UPDATE document_versions SET classification='CONFIDENTIAL' WHERE id=%s",[self.vid])
        self.publish()
        self.assertEqual(portal.current_versions(self.reader,personal=True),[])
        self.assertEqual(portal.pending_acknowledgements(self.reader),[])
        self.assertEqual(s.query('SELECT id FROM acknowledgement_assignments WHERE user_id=%s',[uid]),[])
        doc = s.query('SELECT document_id FROM document_versions WHERE id=%s',[self.vid])[0]['document_id']
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(f'/documents/{doc}/qr/').status_code,403)

    def test_acknowledgements_are_assigned_without_login_version_bound_and_idempotent(self):
        self.distribution()
        self.publish()
        uid = s.actor(self.reader)
        task = s.query('SELECT * FROM acknowledgement_assignments WHERE user_id=%s',[uid])[0]
        self.assertEqual(task['version_id'],self.vid)
        self.assertEqual(task['due_on'],timezone.localdate()+timedelta(days=14))
        portal.synchronize_acknowledgements()
        self.assertEqual(len(s.query('SELECT id FROM acknowledgement_assignments WHERE user_id=%s',[uid])),1)
        with self.assertRaises(PermissionDenied):
            portal.acknowledge(self.outsider,task['id'],True)
        with self.assertRaises(ValidationError):
            portal.acknowledge(self.reader,task['id'],False)
        portal.acknowledge(self.reader,task['id'],True)
        portal.acknowledge(self.reader,task['id'],True)
        self.assertEqual(len(s.query('SELECT * FROM acknowledgement_receipts WHERE assignment_id=%s',[task['id']])),1)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM acknowledgement_receipts WHERE assignment_id=%s',[task['id']])
        self.assertEqual(portal.pending_acknowledgements(self.reader),[])
        new = s.new_revision(self.author,self.vid,'minor','Neue verpflichtende Änderung')
        s.edit_draft(self.author,new,dict(title='Nachfolger',change_summary='Neu',effective_from=timezone.now()-timedelta(minutes=1),next_review_on=timezone.localdate()+timedelta(days=100)))
        s.transition(self.author,new,'submit','Prüfen')
        s.transition(self.reviewer,new,'accept','Prüfung')
        s.transition(self.reviewer,new,'accept','Freigabe')
        self.assertEqual(portal.pending_acknowledgements(self.reader)[0]['version_id'],new)
        with self.assertRaises(PermissionDenied):
            portal.acknowledge(self.reader,task['id'],True)

    def test_revoked_access_blocks_pending_acknowledgement_and_download(self):
        self.distribution()
        self.publish()
        task = portal.pending_acknowledgements(self.reader)[0]
        s.query("DELETE FROM role_assignments WHERE user_id=%s",[s.actor(self.reader)])
        self.assertEqual(portal.pending_acknowledgements(self.reader),[])
        with self.assertRaises(PermissionDenied):
            portal.acknowledge(self.reader,task['id'],True)
        self.assertEqual(s.query('SELECT * FROM acknowledgement_receipts'),[])

    def test_distribution_is_frozen_and_part_of_review_fingerprint(self):
        self.distribution()
        self.assertEqual(s.visible_versions(self.author,search='Maschinenstart')[0]['id'],self.vid)
        s.transition(self.author,self.vid,'submit','Prüfung')
        with self.assertRaises(ValidationError):
            self.distribution(False)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('UPDATE version_distribution SET requires_ack=false WHERE version_id=%s',[self.vid])
        s.transition(self.reviewer,self.vid,'accept','QMB')
        s.transition(self.reviewer,self.vid,'accept','Freigabe')

    def test_personal_workplace_and_bookmarks_do_not_expand_permissions(self):
        self.publish()
        admin = self.admin()
        other = s.query("INSERT INTO departments(code,name) VALUES ('PROD','Produktion') RETURNING id")[0]['id']
        portal.save_workplace(admin,s.actor(self.reader),other,'Halle 1','Maschinenführer',[],'Arbeitsplatzzuordnung')
        self.assertEqual(portal.current_versions(self.reader,personal=True),[])
        self.assertEqual(len(portal.current_versions(self.reader)),1)
        doc = s.get_version(self.author,self.vid)[1]['document_id']
        portal.bookmark(self.reader,doc)
        self.assertTrue(portal.current_versions(self.reader)[0]['bookmarked'])
        portal.bookmark(self.reader,doc)
        self.assertFalse(portal.current_versions(self.reader)[0]['bookmarked'])
        with self.assertRaises(PermissionDenied):
            portal.save_workplace(self.reader,s.actor(self.reader),self.dep,'','',[],'Unberechtigt')
        with self.assertRaises(PermissionDenied):
            portal.bookmark(self.outsider,doc)

    def test_management_menu_is_discoverable_for_it_without_granting_qmb_rights(self):
        admin = self.admin()
        self.client.force_login(admin)
        self.assertNotContains(self.client.get('/'),'Verwaltung')
        self.assertContains(self.client.get('/management/access/'),'IT-Admin')
        self.assertEqual(self.client.get('/management/').status_code,403)
        self.assertEqual(self.client.post('/management/',{'reason':'Versuch'}).status_code,403)
        self.client.force_login(self.reviewer)
        self.assertRedirects(self.client.get('/management/access/'),'/management/',fetch_redirect_response=False)
        self.assertContains(self.client.get('/management/'),'Gültigkeit (Monate)')
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get('/management/access/').status_code,403)
        self.assertEqual(self.client.get('/management/audit/').status_code,403)

    def test_pdf_preview_and_qr_retain_private_permissions_and_control_metadata(self):
        self.publish()
        fid = s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        name,content = previews.reading_pdf(self.reader,self.vid,fid,'http://localhost/documents/1/current/')
        pdf = PdfReader(io.BytesIO(content))
        text = '\n'.join(p.extract_text() for p in pdf.pages)
        self.assertIn('Originalinhalt',text)
        self.assertIn('IT-001',text)
        self.assertIn('Version 1.0',text)
        self.assertIn('Aktualität',text)
        with self.assertRaises(PermissionDenied):
            previews.reading_pdf(self.outsider,self.vid,fid,'http://localhost/')
        self.client.force_login(self.reader)
        response = self.client.get(f'/versions/{self.vid}/files/{fid}/preview/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['X-Frame-Options'],'SAMEORIGIN')
        self.assertIn('no-store',response['Cache-Control'])
        doc = s.get_version(self.author,self.vid)[1]['document_id']
        response = self.client.get(f'/documents/{doc}/qr/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'image/svg+xml')
        self.assertNotIn(b'<script',response.content)

    def test_local_pdfjs_viewer_is_private_and_library_does_not_expose_files(self):
        self.publish()
        fid = s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        self.client.force_login(self.reader)
        response = self.client.get(f'/versions/{self.vid}/files/{fid}/viewer/')
        self.assertContains(response,'pdf-canvas')
        self.assertContains(response,'/assets/pdfjs/6.5.438/viewer.mjs')
        self.assertEqual(response['X-Frame-Options'],'SAMEORIGIN')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertNotIn('unsafe-eval',response['Content-Security-Policy'])
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(f'/versions/{self.vid}/files/{fid}/viewer/').status_code,403)
        self.client.logout()
        response = self.client.get('/assets/pdfjs/6.5.438/pdf.mjs')
        self.assertEqual(response.status_code,200)
        self.assertIn('immutable',response['Cache-Control'])
        # Match Django's streaming test-client cleanup without closing the class transaction.
        from django.core.signals import request_finished
        from django.db import close_old_connections
        request_finished.disconnect(close_old_connections)
        try:
            response.close()
        finally:
            request_finished.connect(close_old_connections)
        self.assertEqual(self.client.get('/assets/pdfjs/6.5.438/../../.local/secrets.json').status_code,404)
        self.assertEqual(self.client.get('/assets/pdfjs/6.5.438/config/settings.py').status_code,404)

    def test_pdf_preview_removes_annotations_and_preserves_source(self):
        from reportlab.pdfgen import canvas
        stream = io.BytesIO()
        c = canvas.Canvas(stream)
        c.drawString(50,700,'PDF Original')
        c.linkURL('https://example.org',(20,20,100,80))
        c.save()
        original = stream.getvalue()
        storage.upload(self.author,self.vid,SimpleUploadedFile('original.pdf',original),'RELEASE')
        self.publish()
        fid = s.query("SELECT f.id FROM file_objects f WHERE f.original_name='original.pdf'")[0]['id']
        _,result = previews.reading_pdf(self.reader,self.vid,fid,'http://localhost/current/')
        self.assertIn('PDF Original',PdfReader(io.BytesIO(result)).pages[0].extract_text())
        self.assertEqual(storage.download(self.reader,self.vid,fid)[1],original)
        with self.assertRaises(ValidationError):
            storage.upload(self.author,self.vid,SimpleUploadedFile('not-pdf.txt',b'x'),'RELEASE')

    def test_runtime_role_can_use_distribution_acknowledgements_and_audit_export(self):
        self.enable_runtime_role()
        self.distribution()
        self.publish()
        task = portal.pending_acknowledgements(self.reader)[0]
        portal.acknowledge(self.reader,task['id'],True)
        self.client.force_login(self.reviewer)
        s.audit(s.actor(self.author),'CSV_TEST',self.vid,'=SUM(1,2)')
        response = self.client.get('/management/audit/',{'export':'csv','action':'CSV_TEST'})
        self.assertEqual(response.status_code,200)
        self.assertIn(b"'=SUM",response.content)
        self.assertNotIn(b'smtp_password',response.content)
        self.assertContains(self.client.get('/management/audit/'),'Kenntnisnahmen je Version')
        response = self.client.get('/management/audit/',{'export':'acknowledgements','document_number':'IT-001'})
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Inhaltsfingerabdruck',response.content)
        self.assertIn(b'IT-001',response.content)

class EvidenceTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def data(self,classification='INTERNAL'):
        return dict(number='N-001',title='Prüfprotokoll',category_id=s.query("SELECT id FROM document_categories WHERE name='Richtlinie'")[0]['id'],
            department_id=self.dep,occurred_on=timezone.localdate()-timedelta(days=60),retain_until=timezone.localdate()-timedelta(days=1),
            source_version_id=None,classification=classification,reason='Abgeschlossene Prüfung')

    def create(self,classification='INTERNAL'):
        return evidence.create_record(self.author,self.data(classification),SimpleUploadedFile('protokoll.txt',b'Unveraenderlicher Nachweis'))

    def test_evidence_is_immutable_and_retention_separate_from_document_review(self):
        rid = self.create()
        self.assertEqual(evidence.download_record(self.reader,rid)[1],b'Unveraenderlicher Nachweis')
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query("UPDATE evidence_records SET title='Manipulation' WHERE id=%s",[rid])
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM evidence_records WHERE id=%s',[rid])
        self.assertEqual(s.query('SELECT * FROM periodic_reviews'),[])

    def test_confidential_evidence_does_not_leak_to_readers_or_it(self):
        rid = self.create('CONFIDENTIAL')
        self.assertEqual(len(evidence.records(self.reviewer)),1)
        self.assertEqual(evidence.records(self.reader),[])
        self.assertEqual(evidence.records(self.outsider),[])
        with self.assertRaises(PermissionDenied):
            evidence.download_record(self.reader,rid)
        self.assertEqual(evidence.download_record(self.author,rid)[1],b'Unveraenderlicher Nachweis')

    def test_retention_cannot_be_shortened_and_hold_blocks_disposal(self):
        rid = self.create()
        _,record = evidence.get_record(self.reviewer,rid)
        with self.assertRaises(ValidationError):
            evidence.change_retention(self.reviewer,rid,record['retention_due']-timedelta(days=1),False,'Verkürzen')
        evidence.change_retention(self.reviewer,rid,record['retention_due'],True,'Audit-Sperre')
        with self.assertRaises(ValidationError):
            evidence.request_disposal(self.reviewer,rid,'Frist abgelaufen')
        evidence.change_retention(self.reviewer,rid,record['retention_due'],False,'Audit abgeschlossen')
        evidence.request_disposal(self.reviewer,rid,'Frist abgelaufen; prüfen')
        evidence.request_disposal(self.reviewer,rid,'Keine doppelte Vormerkung')
        self.assertEqual(len(s.query('SELECT * FROM evidence_disposal_requests')),1)
        self.assertEqual(evidence.download_record(self.reader,rid)[1],b'Unveraenderlicher Nachweis')

    def test_database_rejects_shortening_or_unqualified_retention_actor(self):
        rid = self.create()
        _,record = evidence.get_record(self.reviewer,rid)
        for actor,due in [(self.author,record['retention_due']), (self.reviewer,record['retention_due']-timedelta(days=1))]:
            with self.assertRaises(DatabaseError),transaction.atomic():
                s.query('INSERT INTO evidence_retention_events(record_id,actor_id,retain_until,legal_hold,reason) VALUES (%s,%s,%s,false,%s)',[rid,s.actor(actor),due,'Ungültige Entscheidung'])

    def test_records_require_author_and_defined_retention(self):
        data = self.data()
        with self.assertRaises(PermissionDenied):
            evidence.create_record(self.reader,data,SimpleUploadedFile('x.txt',b'x'))
        data['retain_until'] = None
        with self.assertRaises(ValidationError):
            evidence.create_record(self.author,data,SimpleUploadedFile('x.txt',b'x'))
        s.query('UPDATE document_categories SET retention_months=12 WHERE id=%s',[data['category_id']])
        rid = evidence.create_record(self.author,data,SimpleUploadedFile('x.txt',b'x'))
        from .policies import add_months
        self.assertEqual(evidence.get_record(self.author,rid)[1]['retain_until'],add_months(data['occurred_on'],12))

    def test_record_upload_and_retention_work_with_restricted_runtime_role(self):
        self.enable_runtime_role()
        rid = self.create()
        due = timezone.localdate()+timedelta(days=30)
        evidence.change_retention(self.reviewer,rid,due,True,'Verlängerte Aufbewahrung')
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(f'/records/{rid}/'),'Aussonderungssperre aktiv')
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(f'/records/{rid}/',{'action':'disposal','reason':'Unberechtigt'}).status_code,403)
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('DELETE FROM evidence_retention_events WHERE record_id=%s',[rid])
