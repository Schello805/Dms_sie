from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[('dms','0023_document_number_registry')]
    operations=[migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/024_calendar_validity.sql').read_text())]
