from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[('dms','0015_accounts')]
    operations=[migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/016_masterdata.sql').read_text())]
