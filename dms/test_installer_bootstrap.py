from io import StringIO
from pathlib import Path
import tempfile
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from .services import actor, allowed, query


class InstallerBootstrapTests(TestCase):
    def password_file(self, directory):
        file = Path(directory) / 'password'
        file.write_text('Install-only-Credential-9sZ2b3m8!')
        file.chmod(0o600)
        return file

    def test_bootstrap_is_idempotent_and_does_not_grant_document_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            file = self.password_file(directory)
            call_command('bootstrap_admin','installer-admin',password_file=file,stdout=StringIO())
            admin = get_user_model().objects.get(username='installer-admin')
            self.assertFalse(admin.is_superuser)
            self.assertFalse(admin.is_staff)
            uid = actor(admin)
            self.assertTrue(allowed(uid,None,'ADMIN'))
            self.assertFalse(allowed(uid,None,'AUTHOR'))
            self.assertFalse(query('SELECT is_qmb(%s) AS qmb',[uid])[0]['qmb'])
            encoded = admin.password
            file.write_text('Different-only-Credential-9sZ2b3m8!')
            call_command('bootstrap_admin','installer-admin',password_file=file,stdout=StringIO())
            self.assertEqual(get_user_model().objects.get(pk=admin.pk).password,encoded)

    def test_existing_normal_user_is_never_elevated(self):
        get_user_model().objects.create_user('existing',password='Local-only-Password-2026!')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CommandError):
                call_command('bootstrap_admin','existing',password_file=self.password_file(directory),stdout=StringIO())

    def test_public_password_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            file = self.password_file(directory)
            file.chmod(0o644)
            with self.assertRaises(CommandError):
                call_command('bootstrap_admin','installer-admin',password_file=file,stdout=StringIO())
            self.assertFalse(get_user_model().objects.filter(username='installer-admin').exists())
