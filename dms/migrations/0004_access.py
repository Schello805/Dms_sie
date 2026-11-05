from pathlib import Path
from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0003_review_indexes')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/004_access.sql').read_text())]
