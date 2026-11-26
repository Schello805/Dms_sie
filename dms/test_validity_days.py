from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from django.test import TestCase
from django.utils import timezone
from . import tests as fixtures,services as s
from .validity import ValidityDateField,validity_start


class ValidityDayTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    publish=fixtures.WorkflowTests.publish

    def test_fields_use_dates_and_preserve_local_day_for_existing_values(self):
        from .forms import DocumentUploadForm,EditForm
        for form in (DocumentUploadForm(user=self.author),EditForm()):
            self.assertIsInstance(form.fields['effective_from'],ValidityDateField)
            self.assertEqual(form.fields['effective_from'].widget.input_type,'date')
        field=ValidityDateField()
        self.assertEqual(field.clean('2026-07-15'),date(2026,7,15))
        instant=datetime(2026,7,14,22,30,tzinfo=ZoneInfo('UTC'))
        self.assertEqual(field.prepare_value(instant),date(2026,7,15))
        self.assertEqual(timezone.localtime(validity_start(instant)).hour,0)
        self.assertEqual(timezone.localdate(validity_start(instant)),date(2026,7,15))

    def test_new_validity_is_midnight_but_audit_timestamp_remains_precise(self):
        v=s.get_version(self.author,self.vid)[1]
        self.assertEqual(timezone.localtime(v['effective_from']).time().isoformat(),'00:00:00')
        self.publish()
        self.client.force_login(self.author)
        self.assertContains(self.client.get(f'/versions/{self.vid}/'),'Erstmalig gültig ab: '+timezone.localdate(v['effective_from']).strftime('%d.%m.%Y'))
        self.assertEqual(s.get_version(self.author,self.vid)[1]['created_at'],v['created_at'])
        revision=s.new_revision(self.author,self.vid)
        self.assertEqual(timezone.localtime(s.get_version(self.author,revision)[1]['effective_from']).hour,0)

    def test_legacy_late_time_is_valid_for_entire_local_day_without_mutation(self):
        late=timezone.make_aware(datetime.combine(timezone.localdate(),datetime.max.time()))
        s.query('UPDATE document_versions SET effective_from=%s WHERE id=%s',[late,self.vid])
        self.publish()
        v=s.get_version(self.author,self.vid)[1]
        self.assertEqual(v['effective_from'],late)
        self.assertEqual(s.query('SELECT current_release(%s) AS id',[v['document_id']])[0]['id'],self.vid)
