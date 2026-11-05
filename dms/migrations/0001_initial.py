from pathlib import Path
from django.conf import settings
from django.db import migrations

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2] / 'db/001_initial.sql').read_text().removeprefix('BEGIN;').rsplit('COMMIT;', 1)[0])]
