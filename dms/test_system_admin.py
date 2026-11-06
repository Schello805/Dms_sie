import io
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import DatabaseError
from django.test import TestCase,Client,RequestFactory,override_settings
from django.urls import path
from django.utils import timezone
from . import tests as fixtures,services as s,directory,system_logs
from .system_info import snapshot
from config.urls import urlpatterns as application_urls

SECRET_MARKER = 'NEVER_LOG_PASSWORD_2026'
def diagnostic_crash(request):
    raise RuntimeError('bind_password='+SECRET_MARKER+' SELECT private_data')
urlpatterns = [path('diagnostic-test-crash/',diagnostic_crash,name='diagnostic_test_crash'),*application_urls]
handler500 = 'dms.branding.server_error'
handler403 = 'dms.branding.permission_denied'
handler404 = 'dms.branding.page_not_found'
handler400 = 'dms.branding.bad_request'

class SystemAdministrationTests(TestCase):
    setUp_fixture = fixtures.WorkflowTests.setUp
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def setUp(self):
        self.setUp_fixture()
        self.log_directory = TemporaryDirectory()
        self.addCleanup(self.log_directory.cleanup)
        self.log_override = override_settings(ERROR_LOG_DIR=Path(self.log_directory.name)/'logs')
        self.log_override.enable()
        self.addCleanup(self.log_override.disable)
        self.admin = get_user_model().objects.create_user('it-admin-diagnostics',password='TestPassword-2026!')
        s.query("INSERT INTO users(auth_user_id,display_name,settings_admin) VALUES (%s,'IT-Admin',true)",[self.admin.pk])

    def config_data(self,**changes):
        data = {field:directory.load_config()[field] for field in directory.FIELDS}
        data.update(host='dc01.example.internal',domain='example.internal',base_dn='DC=example,DC=internal',
            bind_identity='svc-dms@example.internal',password='  '+SECRET_MARKER+'  ',clear_password=False,reason='Anbindung vorbereiten')
        data.update(changes)
        return data

    def test_only_it_admin_can_view_or_change_system_and_directory_settings(self):
        for user in (self.author,self.reviewer,self.reader,self.approver):
            self.client.force_login(user)
            for url in ['/settings/system/','/settings/directory/']:
                self.assertEqual(self.client.get(url).status_code,403)
                self.assertEqual(self.client.post(url,self.config_data()).status_code,403)
            with self.assertRaises(PermissionDenied):
                directory.save_config(user,self.config_data())
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/settings/'),'Letzte technische Fehler')
        self.assertContains(self.client.get('/settings/system/'),'PostgreSQL')
        self.assertContains(self.client.get('/settings/directory/'),'Anmeldung weiterhin mit lokalen Benutzern')

    def test_directory_secret_is_encrypted_not_rendered_or_audited_and_save_does_not_connect(self):
        data = self.config_data()
        with patch('socket.create_connection') as connect:
            directory.save_config(self.admin,data)
            connect.assert_not_called()
        config = directory.load_config()
        self.assertNotIn(SECRET_MARKER,config['password_ciphertext'])
        self.assertEqual(directory.cipher().decrypt(config['password_ciphertext'].encode()).decode(),data['password'])
        self.assertNotIn('password_ciphertext',directory.public_config(config))
        audit = s.query("SELECT details FROM audit_events WHERE action='CHANGE_DIRECTORY_SETTINGS'")[0]['details']
        self.assertNotIn(SECRET_MARKER,str(audit))
        self.assertNotIn(config['password_ciphertext'],str(audit))
        self.client.force_login(self.admin)
        response = self.client.get('/settings/directory/')
        self.assertNotContains(response,SECRET_MARKER)
        self.assertNotContains(response,config['password_ciphertext'])
        self.assertContains(response,'Kennwort hinterlegt:')
        directory.save_config(self.admin,self.config_data(password=''))
        self.assertEqual(directory.load_config()['password_ciphertext'],config['password_ciphertext'])
        directory.save_config(self.admin,self.config_data(password='',clear_password=True))
        self.assertEqual(directory.load_config()['password_ciphertext'],'')

    def test_directory_validation_and_csrf_leave_saved_config_unchanged(self):
        for changes in [{'host':'ldap://user:password@example.internal'}, {'security':'NONE'},
            {'user_filter':'(uid=*)'}, {'username_attribute':'invalid)(uid=*'}, {'password':'new','clear_password':True}]:
            with self.assertRaises(ValidationError):
                directory.save_config(self.admin,self.config_data(**changes))
        self.assertEqual(directory.load_config()['host'],'')
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        self.assertEqual(strict.post('/settings/directory/',self.config_data()).status_code,403)
        self.assertEqual(strict.post('/settings/system/',{'action':'test_log'}).status_code,403)

    def test_system_information_is_allowlisted_and_runtime_role_can_save_directory(self):
        self.enable_runtime_role()
        directory.save_config(self.admin,self.config_data())
        info = snapshot()
        self.assertIn('postgres',info)
        self.assertNotIn('PASSWORD',str(info))
        self.assertNotIn(SECRET_MARKER,str(info))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/settings/'),'Freier Dateispeicher')
        self.assertContains(self.client.get('/settings/system/'),'Warteschlange')
        self.assertNotContains(self.client.get('/settings/system/'),SECRET_MARKER)

    def test_request_and_exception_secrets_are_never_persisted(self):
        request = RequestFactory().post('/settings/directory/?password='+SECRET_MARKER,{'password':SECRET_MARKER})
        request.COOKIES['sessionid'] = SECRET_MARKER
        request.resolver_match = SimpleNamespace(route='settings/directory/')
        request.diagnostic_id = 'd659db07-ea5c-480a-99d9-7578b93957a3'
        request.user = self.admin
        try:
            raise ValueError('password='+SECRET_MARKER)
        except ValueError:
            logging.getLogger('dms.system').error('Unsafe message '+SECRET_MARKER,exc_info=True,extra={'request':request})
        root = Path(self.log_override.options['ERROR_LOG_DIR'])
        raw = (root/'errors.jsonl').read_text()
        self.assertNotIn(SECRET_MARKER,raw)
        self.assertNotIn('sessionid',raw)
        rows,warning = system_logs.read_events()
        self.assertEqual(warning,'')
        self.assertEqual(rows[0]['exception_type'],'ValueError')
        self.assertEqual(rows[0]['route'],'settings/directory/')
        self.assertTrue(rows[0]['frames'])
        self.assertEqual((root/'errors.jsonl').stat().st_mode & 0o777,0o600)

    @override_settings(ROOT_URLCONF='dms.test_system_admin',DEBUG=False)
    def test_unhandled_web_error_is_logged_with_request_id(self):
        client = Client(raise_request_exception=False)
        response = client.get('/diagnostic-test-crash/')
        self.assertEqual(response.status_code,500)
        self.assertIn('X-Request-ID',response)
        rows,_ = system_logs.read_events()
        self.assertEqual(rows[0]['exception_type'],'RuntimeError')
        self.assertEqual(rows[0]['request_id'],response['X-Request-ID'])
        self.assertNotIn(SECRET_MARKER,str(rows))
        self.assertNotIn(SECRET_MARKER,response.content.decode())

    def test_log_remains_usable_without_database_and_bad_lines_are_ignored(self):
        with patch('dms.services.query',side_effect=DatabaseError('password='+SECRET_MARKER)):
            logging.getLogger('dms.system').error(SECRET_MARKER)
        root = Path(self.log_override.options['ERROR_LOG_DIR'])
        with (root/'errors.jsonl').open('a') as stream:
            stream.write('not json\n[]\n{"invalid":true}\n')
        rows,warning = system_logs.read_events()
        self.assertEqual(warning,'')
        self.assertEqual(len(rows),1)
        self.assertNotIn(SECRET_MARKER,str(rows))

    def test_rotation_and_parallel_writers_are_bounded(self):
        event = {'at':timezone.now().isoformat(),'level':'ERROR','source':'dms.system','event_code':'APPLICATION_ERROR',
            'exception_type':'ExampleError','route':'','method':'','request_id':'','user_id':None,'frames':[]}
        with patch.object(system_logs,'MAX_BYTES',500):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(system_logs.write_event,[event]*30))
            root = Path(self.log_override.options['ERROR_LOG_DIR'])
            files = list(root.glob('*.jsonl'))
            self.assertLessEqual(len(files),4)
            for path in files:
                self.assertLessEqual(path.stat().st_size,500)
                for line in path.read_text().splitlines():
                    self.assertEqual(json.loads(line)['source'],'dms.system')

    def test_manual_log_test_is_marked_and_shown_in_admin_overview(self):
        self.client.force_login(self.admin)
        response = self.client.post('/settings/system/',{'action':'test_log'})
        self.assertEqual(response.status_code,302)
        rows,_ = system_logs.read_events()
        self.assertEqual(rows[0]['event_code'],'LOG_SELF_TEST')
        self.assertContains(self.client.get('/settings/'),'Protokolltest')
        self.assertContains(self.client.get('/settings/system/'),'kein Anwendungsfehler')
