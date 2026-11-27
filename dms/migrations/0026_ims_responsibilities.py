from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('dms', '0025_editable_document_numbers')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/026_ims_responsibilities.sql').read_text())]
