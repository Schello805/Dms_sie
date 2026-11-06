"""Real CSRF enforcement through an HTTPS edge and an internal HTTP hop."""
import os
import runpy
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings


class ProxyLoginTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user('proxy-reader', password='Proxy-Test-Password-2026!')
        with patch.dict(os.environ, {'DMS_SECRET_KEY':'proxy-test-only', 'DMS_ALLOWED_HOSTS':' dms.proxy.test,localhost ', 'DMS_INTERNAL_HTTP':'1', 'DMS_DEBUG':'0', 'DMS_DYNAMIC_HOSTS':'1', 'DMS_CSRF_TRUSTED_ORIGINS':''}):
            config = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'config/settings.py'))
        self.assertEqual(config['CSRF_TRUSTED_ORIGINS'], ['https://dms.proxy.test','https://localhost'])
        self.override = override_settings(**{key:config[key] for key in ('CSRF_TRUSTED_ORIGINS','EXPLICIT_HOSTS','DYNAMIC_HOSTS','ALLOWED_HOSTS','SECURE_SSL_REDIRECT','CSRF_COOKIE_SECURE','SESSION_COOKIE_SECURE')}, DEBUG=False)
        self.override.enable();self.addCleanup(self.override.disable)
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST='dms.proxy.test', HTTP_X_FORWARDED_PROTO='http')
        self.assertEqual(self.client.get('/login/').status_code,200)
        self.token = self.client.cookies['csrftoken'].value

    def submit(self, origin, token=True):
        data = {'username':'proxy-reader','password':'Proxy-Test-Password-2026!'}
        if token: data['csrfmiddlewaretoken'] = self.token
        return self.client.post('/login/', data, HTTP_ORIGIN=origin, HTTP_REFERER=origin+'/login/')

    def test_https_domain_login_survives_internal_http_proxy(self):
        self.assertEqual(self.submit('https://dms.proxy.test').status_code,302)
        self.assertIn('_auth_user_id',self.client.session)

    def test_unconfigured_origin_is_rejected(self):
        self.assertEqual(self.submit('https://attacker.test').status_code,403)
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_configured_origin_still_requires_csrf_token(self):
        self.assertEqual(self.submit('https://dms.proxy.test',token=False).status_code,403)

    def test_local_http_login_still_works(self):
        local = Client(enforce_csrf_checks=True, HTTP_HOST='192.168.10.20')
        self.assertEqual(local.get('/login/').status_code,200)
        result = local.post('/login/', {'username':'proxy-reader','password':'Proxy-Test-Password-2026!', 'csrfmiddlewaretoken':local.cookies['csrftoken'].value}, HTTP_ORIGIN='http://192.168.10.20')
        self.assertEqual(result.status_code,302)
