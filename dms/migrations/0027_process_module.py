from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('dms','0026_ims_responsibilities')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/027_process_module.sql').read_text())]
