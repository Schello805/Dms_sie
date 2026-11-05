from pathlib import Path
from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0005_lifecycle')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/006_fulltext.sql').read_text())]
