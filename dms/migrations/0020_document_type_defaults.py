from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[('dms','0019_qmb_upload')]
    operations=[migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/020_document_type_defaults.sql').read_text())]
