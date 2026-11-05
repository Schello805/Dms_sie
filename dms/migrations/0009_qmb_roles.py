from pathlib import Path
from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0008_email_reminders')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/009_qmb_roles.sql').read_text())]
