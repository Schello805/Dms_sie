from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('dms', '0029_process_demo')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2] / 'db/030_process_bpmn.sql').read_text())]
