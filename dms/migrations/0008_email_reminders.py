from pathlib import Path
from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0007_category_reviews')]
    operations = [migrations.RunSQL((Path(__file__).resolve().parents[2]/'db/008_email_reminders.sql').read_text())]
