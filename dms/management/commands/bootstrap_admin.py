"""One-time initial IT account; no Django superuser or document privileges."""
from pathlib import Path
import stat
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from dms.services import query


class Command(BaseCommand):
    help = 'Initialen IT-Admin aus einer geschützten Passwortdatei anlegen; vorhandene Konten niemals hochstufen.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--password-file', required=True, type=Path)

    @transaction.atomic
    def handle(self, *args, **options):
        username = options['username']
        existing = get_user_model().objects.filter(username=username).first()
        if existing:
            if not existing.is_active or not query("SELECT 1 FROM users WHERE auth_user_id=%s AND active AND has_role(id,'ADMIN',NULL,NULL)", [existing.pk]):
                raise CommandError('Vorhandenes Konto wird nicht zum Administrator hochgestuft.')
            self.stdout.write('Initialer Administrator besteht bereits; Passwort unverändert.')
            return
        file = options['password_file']
        try:
            if file.is_symlink() or stat.S_IMODE(file.stat().st_mode) & 0o077:
                raise CommandError('Passwortdatei muss privat sein (0600).')
            password = file.read_text().rstrip('\n')
        except OSError:
            raise CommandError('Passwortdatei nicht lesbar.')
        user = get_user_model()(username=username)
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages))
        user.set_password(password)
        user.save()
        call_command('provision_dms', username, role='ADMIN', department='*', department_name=None, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS('Initialer IT-Administrator angelegt; keine Autor-/QMB-Rechte.'))
