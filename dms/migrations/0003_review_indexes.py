from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [('dms','0002_workflow')]
    operations = [migrations.RunSQL('CREATE INDEX reviews_latest ON periodic_reviews(version_id, id DESC);')]
