from pathlib import Path
from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0004_access')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/005_lifecycle.sql').read_text())]
