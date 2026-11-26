from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[('dms','0024_calendar_validity')]
    operations=[migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/025_editable_document_numbers.sql').read_text())]
