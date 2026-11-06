from pathlib import Path
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('dms','0018_optional_user_reason')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/019_qmb_upload.sql').read_text())]
