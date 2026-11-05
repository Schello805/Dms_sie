import io
import json
from pathlib import Path
import zipfile
from datetime import timedelta
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError,transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from . import indexing,services as s,storage
from . import tests as workflow_fixtures
from django.test import TestCase

# Reuse the existing fixture, but do not inherit its test methods again.
class IndexingTests(TestCase):
    setUp = workflow_fixtures.WorkflowTests.setUp
    publish = workflow_fixtures.WorkflowTests.publish
    enable_runtime_role = workflow_fixtures.WorkflowTests.enable_runtime_role
    def test_real_txt_extraction_and_content_search(self):
        self.assertTrue(indexing.process_one())
        self.assertFalse(indexing.process_one())
        self.assertEqual(s.query('SELECT status FROM file_text_indexes')[0]['status'],'READY')
        self.publish()
        results = s.visible_versions(self.reader,search='Originalinhalt')
        self.assertEqual([v['id'] for v in results],[self.vid])
        self.assertIn('Originalinhalt',results[0]['snippet'])
        self.assertEqual(s.visible_versions(self.outsider,search='Originalinhalt'),[])

    def test_index_does_not_bypass_confidentiality_or_withdrawal(self):
        indexing.process_one()
        self.publish()
        s.change_access(self.author,self.vid,'EXPLICIT',[s.actor(self.author),s.actor(self.approver)],[],'Vertraulich beschränken')
        self.assertEqual(s.visible_versions(self.reader,search='Originalinhalt'),[])
        self.assertEqual(len(s.visible_versions(self.author,search='Originalinhalt')),1)
        s.lifecycle_action(self.reviewer,self.vid,'withdraw','Rückzug',True)
        self.assertEqual(s.visible_versions(self.reader,search='Originalinhalt'),[])

    def test_integrity_failure_is_not_indexed(self):
        f = s.query('SELECT * FROM file_objects')[0]
        (Path(self.media.name)/f['storage_key']).write_bytes(b'Manipulierter Suchtext')
        indexing.process_one()
        row = s.query('SELECT * FROM file_text_indexes')[0]
        self.assertEqual(row['status'],'FAILED')
        self.assertEqual(row['error_code'],'INTEGRITY_FAILURE')
        self.assertEqual(row['text_content'],'')

    def test_stale_worker_cannot_overwrite_new_lease(self):
        job = indexing.claim_job()
        s.query("UPDATE file_text_indexes SET claimed_at=clock_timestamp()-interval '3 minutes'")
        replacement = indexing.claim_job()
        self.assertNotEqual(job['lease_token'],replacement['lease_token'])
        self.assertEqual(indexing.finish_job(job,{'text':'Veraltet'}),[])
        indexing.finish_job(replacement,{'text':'Aktueller Inhalt'})
        self.assertEqual(s.query('SELECT text_content FROM file_text_indexes')[0]['text_content'],'Aktueller Inhalt')

    def test_reindex_authorization_and_worker_fencing(self):
        job = indexing.claim_job()
        with self.assertRaises(PermissionDenied):
            indexing.retry_index(self.reader,self.vid,job['file_id'])
        indexing.retry_index(self.author,self.vid,job['file_id'])
        self.assertEqual(indexing.finish_job(job,{'text':'Nicht übernehmen'}),[])
        self.assertEqual(s.query('SELECT status FROM file_text_indexes')[0]['status'],'PENDING')
        self.assertTrue(s.query("SELECT 1 FROM audit_events WHERE action='REINDEX'"))

    def test_docx_xlsx_and_odt_extraction_in_child_process(self):
        fixtures = [
            ('docx',{'word/document.xml':'<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>Energieverbrauch monatlich prüfen</w:t></w:r></w:p></w:body></w:document>'}),
            ('xlsx',{'xl/workbook.xml':'<workbook><sheets><sheet name="Energiedaten"/></sheets></workbook>','xl/sharedStrings.xml':'<sst><si><t>Energieverbrauch monatlich prüfen</t></si></sst>','xl/worksheets/sheet1.xml':'<worksheet><sheetData><row><c t="s"><v>0</v></c><c t="inlineStr"><is><t>Messstelle</t></is></c></row></sheetData></worksheet>'}),
            ('odt',{'content.xml':'<document><text><p>Energieverbrauch monatlich prüfen</p></text></document>'})]
        for extension,files in fixtures:
            with self.subTest(extension=extension):
                content = io.BytesIO()
                with zipfile.ZipFile(content,'w',zipfile.ZIP_DEFLATED) as archive:
                    for name,text in files.items():
                        archive.writestr(name,text)
                storage.upload(self.author,self.vid,SimpleUploadedFile('test.'+extension,content.getvalue()))
        while indexing.process_one():
            pass
        rows = s.query('SELECT text_content,status FROM file_text_indexes WHERE file_id<>(SELECT min(file_id) FROM file_text_indexes)')
        self.assertEqual(len(rows),3)
        for row in rows:
            self.assertEqual(row['status'],'READY')
            self.assertIn('Energieverbrauch',row['text_content'])
        self.assertEqual(len(s.visible_versions(self.author,search='Energieverbrauch')),1)

    def test_xml_entities_rejected_and_html_snippets_escaped(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content,'w') as archive:
            archive.writestr('word/document.xml','<!DOCTYPE x [<!ENTITY a "unsafe">]><document><t>&a;</t></document>')
        storage.upload(self.author,self.vid,SimpleUploadedFile('entity.docx',content.getvalue()))
        storage.upload(self.author,self.vid,SimpleUploadedFile('markup.txt',b'Energieverbrauch <script>alert(42)</script> ist dokumentiert.'))
        while indexing.process_one():
            pass
        self.assertTrue(s.query("SELECT 1 FROM file_text_indexes WHERE status='FAILED' AND error_code='INVALID_FILE'"))
        self.client.force_login(self.author)
        response = self.client.get('/',{'q':'Energieverbrauch'})
        self.assertContains(response,'Energieverbrauch')
        self.assertNotContains(response,'<script>')

    def test_text_limit_and_empty_scan_status(self):
        storage.upload(self.author,self.vid,SimpleUploadedFile('long.txt',('Energiedaten '*20000).encode()))
        while indexing.process_one():
            pass
        rows = s.query('SELECT length(text_content) AS length,truncated FROM file_text_indexes ORDER BY file_id DESC')
        self.assertEqual(rows[0]['length'],200000)
        self.assertTrue(rows[0]['truncated'])
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100,height=100)
        stream = io.BytesIO()
        writer.write(stream)
        storage.upload(self.author,self.vid,SimpleUploadedFile('scan.pdf',stream.getvalue()))
        indexing.process_one()
        self.assertEqual(s.query('SELECT status FROM file_text_indexes ORDER BY file_id DESC LIMIT 1')[0]['status'],'EMPTY')

    def test_pdf_text_extraction(self):
        data = b'BT /F1 12 Tf 10 100 Td (Energieverbrauch monatlich messen) Tj ET'
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(data)).encode()+b' >>\nstream\n'+data+b'\nendstream']
        pdf = b'%PDF-1.4\n'
        offsets = [0]
        for number,obj in enumerate(objects,1):
            offsets.append(len(pdf))
            pdf += str(number).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
        xref = len(pdf)
        pdf += b'xref\n0 6\n0000000000 65535 f \n'
        pdf += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
        pdf += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF'
        storage.upload(self.author,self.vid,SimpleUploadedFile('energie.pdf',pdf))
        while indexing.process_one():
            pass
        self.assertEqual(len(s.visible_versions(self.author,search='monatlich messen')),1)
        self.assertEqual(len(s.visible_versions(self.author,search='"monatlich messen"')),1)
        self.assertEqual(s.visible_versions(self.author,search='"messen monatlich"'),[])

    def test_queue_retries_are_bounded(self):
        for attempt in range(3):
            self.assertIsNotNone(indexing.claim_job())
            s.query("UPDATE file_text_indexes SET claimed_at=clock_timestamp()-interval '3 minutes'")
        self.assertIsNone(indexing.claim_job())
        self.assertEqual(s.query('SELECT status FROM file_text_indexes')[0]['status'],'FAILED')

    def test_retry_endpoint_requires_post_and_role(self):
        file_id = s.query('SELECT id FROM file_objects')[0]['id']
        self.client.force_login(self.author)
        url = f'/versions/{self.vid}/files/{file_id}/reindex/'
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(self.client.post(url).status_code,302)
        self.publish()
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(url).status_code,403)


    def test_worker_database_role_cannot_read_users_or_change_files(self):
        from django.db import connection
        from django.conf import settings
        with connection.cursor() as cursor:
            cursor.execute('CREATE ROLE ims_index_test NOLOGIN')
            cursor.execute((settings.BASE_DIR/'db/index_grants.sql').read_text().replace(':"index_role"','ims_index_test').replace(':"database_name"',connection.settings_dict['NAME']))
            cursor.execute('SET LOCAL ROLE ims_index_test')
        self.assertTrue(indexing.process_one())
        self.assertEqual(s.query('SELECT status FROM file_text_indexes')[0]['status'],'READY')
        for sql in ['SELECT * FROM users',"UPDATE file_objects SET original_name='Unzulässig'",'SELECT * FROM document_versions']:
            with self.assertRaises(DatabaseError),transaction.atomic():
                s.query(sql)

    def test_private_search_responses_are_not_cacheable(self):
        indexing.process_one()
        self.client.force_login(self.author)
        response = self.client.get('/',{'q':'Originalinhalt'})
        self.assertContains(response,'Originalinhalt')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn('private',response['Cache-Control'])
