from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[('dms','0020_document_type_defaults')]
    operations=[migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/021_readable_document_links.sql').read_text())]
