from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[('dms','0022_qmb_direct_release')]
    operations=[migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/023_document_number_registry.sql').read_text())]
