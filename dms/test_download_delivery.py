import hashlib
import tracemalloc
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from . import services as s, storage, tests as fixtures


class DownloadDeliveryTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    publish = fixtures.WorkflowTests.publish

    def test_original_download_does_not_buffer_the_entire_file(self):
        size = 12 * 1024 * 1024
        storage.upload(self.author, self.vid, SimpleUploadedFile('large.txt', b'x' * size))
        file = s.query("SELECT id,sha256 FROM file_objects WHERE original_name='large.txt'")[0]
        self.publish()
        tracemalloc.start()
        try:
            response = self.client.get(f'/versions/{self.vid}/files/{file["id"]}/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(int(response['Content-Length']), size)
            digest = hashlib.sha256()
            count = 0
            for chunk in response.streaming_content:
                count += len(chunk)
                digest.update(chunk)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(count, size)
        self.assertEqual(digest.hexdigest(), file['sha256'])
        self.assertLess(peak, 6 * 1024 * 1024, f'Download buffers too much memory: {peak} bytes')
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_corrupt_and_missing_files_fail_before_streaming_and_keep_app_available(self):
        from pathlib import Path
        from django.conf import settings
        from django.test import override_settings
        from .system_logs import read_events
        self.publish()
        file=s.query('SELECT * FROM file_objects')[0]
        path=Path(settings.MEDIA_ROOT)/file['storage_key']
        url=f'/versions/{self.vid}/files/{file["id"]}/'
        with override_settings(ERROR_LOG_DIR=Path(self.media.name)/'logs'):
            path.write_bytes(b'Corrupt')
            response=self.client.get(url)
            self.assertEqual(response.status_code,409)
            self.assertFalse(response.streaming)
            self.assertContains(response,'Anfrage-ID:',status_code=409)
            self.assertEqual(read_events()[0][0]['error_code'],'FILE_INTEGRITY')
            path.unlink()
            self.assertEqual(self.client.get(url).status_code,409)
            self.assertEqual(read_events()[0][0]['error_code'],'FILE_UNAVAILABLE')
        self.assertEqual(self.client.get('/').status_code,200)

    def test_pdf_response_uses_a_real_descriptor_and_does_not_leave_generated_files(self):
        from pathlib import Path
        self.publish()
        file=s.query('SELECT id FROM file_objects')[0]
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        from .portal_views import preview_pdf
        request=RequestFactory().get('/preview/?download=1')
        request.user=AnonymousUser()
        response=preview_pdf(request,self.vid,file['id'])
        self.assertEqual(response.status_code,200)
        with response.file_to_stream as source:
            self.assertIsInstance(source.fileno(),int)
            self.assertFalse(Path(source.name).exists())
            self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
        self.assertEqual(self.client.get('/').status_code,200)

    def test_busy_renderer_does_not_block_original_download(self):
        from .preview_resources import render_slot
        self.publish()
        file=s.query('SELECT id FROM file_objects')[0]
        with render_slot():
            response=self.client.get(f'/versions/{self.vid}/files/{file["id"]}/preview/')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response['Retry-After'],'3')
            response=self.client.get(f'/versions/{self.vid}/files/{file["id"]}/')
            self.assertEqual(b''.join(response.streaming_content),b'Originalinhalt')
        self.assertEqual(self.client.get(f'/versions/{self.vid}/files/{file["id"]}/preview/').status_code,200)

    def test_invalid_pdf_gives_a_controlled_error_and_original_is_still_available(self):
        storage.upload(self.author,self.vid,SimpleUploadedFile('bad.pdf',b'Not a PDF'))
        file=s.query("SELECT id FROM file_objects WHERE original_name='bad.pdf'")[0]
        self.publish()
        response=self.client.get(f'/versions/{self.vid}/files/{file["id"]}/preview/')
        self.assertEqual(response.status_code,409)
        self.assertContains(response,'Original herunterladen',status_code=409)
        response=self.client.get(f'/versions/{self.vid}/files/{file["id"]}/')
        self.assertEqual(b''.join(response.streaming_content),b'Not a PDF')
        self.assertEqual(self.client.get('/').status_code,200)

    def test_verified_snapshot_survives_a_change_to_the_original_path(self):
        from pathlib import Path
        from django.conf import settings
        self.publish()
        file=s.query('SELECT * FROM file_objects')[0]
        _,source=storage.open_download(self.reader,self.vid,file['id'])
        with source:
            (Path(settings.MEDIA_ROOT)/file['storage_key']).write_bytes(b'Changed after verification')
            self.assertEqual(source.read(),b'Originalinhalt')

    def test_audit_failure_closes_the_verified_source(self):
        from unittest.mock import patch
        from pathlib import Path
        from django.conf import settings
        self.publish()
        file=s.query('SELECT * FROM file_objects')[0]
        source=(Path(settings.MEDIA_ROOT)/file['storage_key']).open('rb')
        with patch('dms.file_delivery.open_verified',return_value=source),patch('dms.services.audit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):storage.open_download(self.reader,self.vid,file['id'])
        self.assertTrue(source.closed)


from django.test import SimpleTestCase


class DeliveryResourceTests(SimpleTestCase):
    def test_filename_cannot_create_headers_or_paths(self):
        from .file_delivery import safe_filename
        self.assertEqual(safe_filename('C:\\temp\\Bericht\r\nX-Test.txt'),'BerichtX-Test.txt')
        self.assertEqual(safe_filename('../Qualität.pdf'),'Qualität.pdf')
        self.assertEqual(safe_filename('\x00'),'Dokument')

    def test_container_pressure_rejects_rendering_and_reserves_memory(self):
        from unittest.mock import patch
        from .preview_resources import memory_budget, MIB
        from django.core.exceptions import ValidationError
        def available(path,*args,**kwargs):
            if str(path).endswith('memory.max'):return str(512*MIB)
            if str(path).endswith('memory.current'):return str(400*MIB)
            raise FileNotFoundError
        with patch('pathlib.Path.read_text',available):
            with self.assertRaises(ValidationError) as raised:memory_budget()
        self.assertEqual(raised.exception.code,'PDF_MEMORY')
