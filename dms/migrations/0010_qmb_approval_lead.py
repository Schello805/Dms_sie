from pathlib import Path
from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0009_qmb_roles')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/010_qmb_approval_lead.sql').read_text())]
