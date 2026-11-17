from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[('dms','0021_readable_document_links')]
    operations=[migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/022_qmb_direct_release.sql').read_text())]
