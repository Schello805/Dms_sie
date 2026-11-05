import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = 'Lokales Benutzerkonto ohne administrative Django-Rechte interaktiv anlegen.'
    def add_arguments(self, parser):
        parser.add_argument('username')
    def handle(self, *args, **options):
        model = get_user_model()
        if model.objects.filter(username=options['username']).exists():
            raise CommandError('Benutzer existiert bereits.')
        user = model(username=options['username'])
        password = getpass.getpass('Passwort: ')
        if password != getpass.getpass('Passwort wiederholen: '):
            raise CommandError('Passwörter stimmen nicht überein.')
        try:
            validate_password(password,user=user)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages))
        user.set_password(password)
        from django.db import transaction
        from dms.services import query
        with transaction.atomic():
            user.save()
            uid = query('INSERT INTO users(display_name,email,auth_user_id) VALUES (%s,%s,%s) RETURNING id',[user.username,user.email,user.pk])[0]['id']
            query("INSERT INTO role_assignments(user_id,role) VALUES (%s,'READER')",[uid])
        self.stdout.write(self.style.SUCCESS('Benutzer angelegt. Anschließend provision_dms ausführen.'))
