from pathlib import Path
from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0010_qmb_approval_lead')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/011_employee_portal.sql').read_text())]
