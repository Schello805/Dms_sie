import csv
import io
import smtplib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from . import tests as fixtures, services as s, responsibilities, portal, storage


class IMSImprovementsTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    publish = fixtures.WorkflowTests.publish
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def test_reader_and_guest_department_column_filter_sort_and_lazy_fragment(self):
        self.publish()
        other = s.query("INSERT INTO departments(code,name) VALUES ('AA','A-Abteilung') RETURNING id")[0]['id']
        s.query("INSERT INTO role_assignments(user_id,role,department_id) VALUES (%s,'AUTHOR',%s)",[s.actor(self.author),other])
        vid = s.create_document(self.author,dict(number='AA-2',document_type='Richtlinie',department=other,title='Andere Abteilung',effective_from=timezone.now()))
        storage.upload(self.author,vid,SimpleUploadedFile('x.txt',b'Abteilungssuche'))
        s.transition(self.author,vid,'submit','Test');s.transition(self.reviewer,vid,'accept','Test');s.transition(self.reviewer,vid,'accept','Test')
        for user in (None,self.reader):
            self.client.force_login(user) if user else self.client.logout()
            page = self.client.get('/documents/',{'sort':'department'})
            self.assertContains(page,'<td>IT</td>',html=True)
            self.assertContains(page,'sort=department')
            self.assertLess(page.content.index(b'AA-2</a>'),page.content.index(b'IT-001</a>'))
            page = self.client.get('/documents/',{'sort':'department','direction':'desc'})
            self.assertLess(page.content.index(b'IT-001</a>'),page.content.index(b'AA-2</a>'))
            response=self.client.get('/documents/',{'department':self.dep,'sort':'department','fragment':'1'}).json()
            self.assertEqual(response['total_count'],1)
            self.assertIn('IT-001',response['html']);self.assertNotIn('AA-2',response['html'])
            self.assertEqual(response['html'].count('<td'),10)

    def test_transfer_preserves_authorship_link_and_returns_move_to_successor(self):
        target=s.actor(self.approver)
        s.query("INSERT INTO role_assignments(user_id,role,department_id) VALUES (%s,'AUTHOR',%s)",[target,self.dep])
        s.transition(self.author,self.vid,'submit','Test');s.transition(self.reviewer,self.vid,'return','Bitte korrigieren')
        document=s.get_version(self.author,self.vid)[1]['document_id']
        from .document_links import document_url
        before=document_url(document)
        self.enable_runtime_role()
        self.assertEqual(responsibilities.transfer(self.reviewer,s.actor(self.author),target,[document]),1)
        from .simple_workflow import returned_tasks
        self.assertEqual(returned_tasks(self.author),[])
        self.assertEqual(returned_tasks(self.approver)[0]['id'],self.vid)
        self.assertEqual(s.get_version(self.approver,self.vid)[1]['created_by'],s.actor(self.author))
        self.assertEqual(document_url(document),before)
        self.assertEqual(s.visible_versions(self.approver,catalog_only=True)[0]['id'],self.vid)
        s.edit_draft(self.approver,self.vid,dict(title='Übernommen',effective_from=timezone.now()))
        self.assertEqual(len(s.query("SELECT 1 FROM audit_events WHERE action='TRANSFER_RESPONSIBILITY'")),1)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get('/management/responsibilities/').status_code,200)

    def test_transfer_to_qmb_needs_no_additional_author_role(self):
        document=s.get_version(self.author,self.vid)[1]['document_id']
        self.enable_runtime_role()
        responsibilities.transfer(self.reviewer,s.actor(self.author),s.actor(self.reviewer),[document])
        self.assertEqual(s.get_version(self.reviewer,self.vid)[1]['owner_id'],s.actor(self.reviewer))
        self.client.force_login(self.reviewer)
        response=self.client.get('/management/audit/',{'export':'csv','document_number':'IT-001','action':'TRANSFER_RESPONSIBILITY'})
        self.assertContains(response,'TRANSFER_RESPONSIBILITY')
        self.assertContains(response,'historical_authorship_preserved')
        self.assertTrue(s.allowed(s.actor(self.reviewer),self.dep,'AUTHOR',document))

    def test_transfer_refuses_unauthorized_ineligible_or_stale_requests(self):
        document=s.get_version(self.author,self.vid)[1]['document_id']
        for user in (self.author,self.reader,self.approver):
            with self.assertRaises(PermissionDenied):responsibilities.transfer(user,s.actor(self.author),s.actor(self.outsider),[document])
        with self.assertRaises(ValidationError):responsibilities.transfer(self.reviewer,s.actor(self.author),s.actor(self.outsider),[document])
        with self.assertRaises(ValidationError):responsibilities.transfer(self.reviewer,s.actor(self.outsider),s.actor(self.author),[document])
        self.assertEqual(s.get_version(self.author,self.vid)[1]['owner_id'],s.actor(self.author))
        self.enable_runtime_role()
        with self.assertRaises(DatabaseError),transaction.atomic():
            s.query('UPDATE documents SET owner_id=%s WHERE id=%s',[s.actor(self.outsider),document])

    def test_qmb_can_restrict_release_and_reopen_without_changing_default_or_link(self):
        self.publish()
        v=s.get_version(self.author,self.vid)[1]
        from .document_links import document_url
        stable=document_url(v['document_id'])
        file_id=s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        self.assertEqual(self.client.get(stable).status_code,302)
        self.enable_runtime_role()
        policy=s.access_policy(v['document_id'])
        kwargs=dict(access_mode=policy['access_mode'],users=[r['user_id'] for r in policy['users']],groups=[],reason='',login_required=True)
        with self.assertRaises(PermissionDenied):s.change_access(self.author,self.vid,**kwargs)
        s.change_access(self.reviewer,self.vid,**kwargs)
        for url in (stable,f'/versions/{self.vid}/files/{file_id}/',f'/versions/{self.vid}/files/{file_id}/viewer/',f'/versions/{self.vid}/files/{file_id}/preview/',f'/documents/{v["document_id"]}/qr/'):
            self.assertEqual(self.client.get(url).status_code,403,url)
        self.assertNotContains(self.client.get('/documents/'),'IT-001')
        self.client.force_login(self.reader)
        self.assertContains(self.client.get('/documents/'),'IT-001')
        self.assertEqual(self.client.get(stable).status_code,302)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(stable).status_code,403)
        s.change_access(self.reviewer,self.vid,**dict(kwargs,login_required=False))
        self.client.logout();self.assertEqual(self.client.get(stable).status_code,302)

    def test_reader_acknowledgement_visible_only_for_target_user_and_current_version(self):
        portal.save_distribution(self.author,self.vid,'SUBSTANTIAL',True,14,'',[],'')
        self.publish()
        self.client.force_login(self.reader)
        page=self.client.get('/documents/')
        self.assertContains(page,'Für dich zu lesen und zu bestätigen')
        assignment=portal.pending_acknowledgements(self.reader)[0]
        file_id=s.query('SELECT file_id FROM version_files WHERE version_id=%s',[self.vid])[0]['file_id']
        viewer=self.client.get(f'/versions/{self.vid}/files/{file_id}/viewer/')
        self.assertContains(viewer,'Kenntnisnahme bestätigen')
        self.assertContains(viewer,'Was hat sich geändert?')
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(f'/acknowledgements/{assignment["id"]}/',{'confirmed':'on'}).status_code,403)
        self.client.force_login(self.reader)
        response=self.client.post(f'/acknowledgements/{assignment["id"]}/',{'confirmed':'on'})
        self.assertEqual(response.status_code,302)
        self.assertNotContains(self.client.get('/documents/'),'Für dich zu lesen und zu bestätigen')
        self.client.logout();self.assertNotContains(self.client.get('/documents/'),'Kenntnisnahme bestätigen')

    def test_due_today_is_not_overdue_and_expired_review_does_not_hide_release(self):
        s.edit_draft(self.author,self.vid,dict(title='Heute',effective_from=timezone.now(),next_review_on=timezone.localdate()))
        self.publish()
        self.assertFalse(s.visible_versions(self.reader,catalog_only=True)[0]['review_overdue'])
        with patch('dms.catalog_service.timezone.localdate',return_value=timezone.localdate()+timedelta(days=1)):
            self.assertTrue(s.visible_versions(self.reader,catalog_only=True)[0]['review_overdue'])

    def test_qmb_document_audit_export_contains_review_department_and_stable_link(self):
        self.publish();self.client.force_login(self.reviewer)
        response=self.client.get('/management/audit/',{'export':'documents'})
        rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(rows[0][3],'Abteilung');self.assertEqual(rows[1][0],'IT-001')
        self.assertEqual(rows[1][3],'IT');self.assertEqual(rows[1][4],'author')
        self.assertIn('/d/',rows[1][14]);self.assertEqual(rows[1][10],'reviewer')
        for user in (self.author,self.reader,self.approver):
            self.client.force_login(user)
            self.assertEqual(self.client.get('/management/audit/',{'export':'documents'}).status_code,403)

    @override_settings(MALWARE_SCAN_ENABLED=True)
    def test_scanner_infection_and_outage_leave_no_linked_file(self):
        from pathlib import Path
        from django.conf import settings
        before=s.query('SELECT count(*) AS n FROM file_objects')[0]['n']
        for code in (1,2):
            with patch('dms.malware.shutil.which',return_value='/usr/bin/clamdscan'),patch('dms.malware.subprocess.run',return_value=SimpleNamespace(returncode=code)):
                with self.assertRaises(ValidationError):storage.upload(self.author,self.vid,SimpleUploadedFile('bad.txt',b'Blocked'))
            self.assertEqual(s.query('SELECT count(*) AS n FROM file_objects')[0]['n'],before)
            self.assertEqual(len(list(Path(settings.MEDIA_ROOT).iterdir())),1)


class IMSBackgroundTests(SimpleTestCase):
    def test_search_highlights_escape_html_and_mark_only_delimited_hits(self):
        from .templatetags.catalog_text import search_highlights
        result=str(search_highlights('<img src=x onerror=x> __IMS_HIT_START__<script>__IMS_HIT_END__'))
        self.assertIn('&lt;img',result);self.assertIn('<mark>&lt;script&gt;</mark>',result)
        self.assertNotIn('<script>',result)

    def test_only_definite_temporary_smtp_failures_are_retryable(self):
        from .notifications import retryable_failure
        self.assertTrue(retryable_failure(smtplib.SMTPDataError(451,b'later')))
        self.assertFalse(retryable_failure(smtplib.SMTPDataError(550,b'rejected')))
        self.assertFalse(retryable_failure(TimeoutError()))

    def test_ocr_is_used_only_for_pages_without_text_and_limits_are_explicit(self):
        from .extract_text import extract
        blank=SimpleNamespace(extract_text=lambda:'')
        page=SimpleNamespace(extract_text=lambda:'Normaler extrahierter Inhalt aus einer PDF-Seite')
        with patch('pypdf.PdfReader',return_value=SimpleNamespace(is_encrypted=False,pages=[page,blank])),patch('dms.extract_text.scan_page_text',return_value='OCR erkannter Text') as ocr:
            result=extract(b'pdf','pdf')
        self.assertIn('OCR erkannter Text',result['text']);self.assertFalse(result['truncated']);ocr.assert_called_once_with(blank)
        with patch('pypdf.PdfReader',return_value=SimpleNamespace(is_encrypted=False,pages=[blank]*11)),patch('dms.extract_text.scan_page_text',return_value='OCR') as ocr:
            result=extract(b'pdf','pdf')
        self.assertEqual(ocr.call_count,10);self.assertTrue(result['truncated'])
