from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('dms','0016_masterdata')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/017_workflow_fixes.sql').read_text())]
