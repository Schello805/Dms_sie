import inspect
from pathlib import Path
from django import forms
from django.test import TestCase
from . import tests as fixtures, test_improvements as improvements, services as s
from . import forms as document_forms, account_forms, master_forms, admin_forms, portal_forms
from . import masterdata, notifications
from .audit_text import DEFAULT_REASON
from .simple_workflow import decide


class OptionalChangeReasonTests(TestCase):
    setUp=fixtures.WorkflowTests.setUp
    admin=improvements.ImprovementTests.admin
    enable_runtime_role=fixtures.WorkflowTests.enable_runtime_role

    def test_every_general_explanation_field_is_optional_and_bounded(self):
        count=0
        for module in (document_forms,account_forms,master_forms,admin_forms,portal_forms):
            for _, cls in inspect.getmembers(module,inspect.isclass):
                if not issubclass(cls,forms.Form):continue
                for name,field in cls.base_fields.items():
                    if name not in ('reason','rationale','change_summary'):continue
                    self.assertFalse(field.required,(cls.__name__,name))
                    self.assertEqual(field.clean('   '),DEFAULT_REASON)
                    self.assertIn('(optional)',field.label)
                    count+=1
        self.assertGreater(count,20)

    def test_category_group_and_mail_policy_save_without_reason_and_remain_audited(self):
        admin=self.admin();self.enable_runtime_role();self.client.force_login(self.reviewer)
        response=self.client.post('/management/master/categories/new/',{'name':'Optionale Erläuterung','review_interval_months':24,'storage_location_id':1,'active':'on'})
        self.assertEqual(response.status_code,302)
        category=s.query("SELECT id FROM document_categories WHERE display_name='Optionale Erläuterung'")[0]['id']
        self.assertEqual(s.query("SELECT reason FROM audit_events WHERE object_type='master_data' AND object_id=%s ORDER BY id DESC LIMIT 1",['categories:'+str(category)])[0]['reason'],DEFAULT_REASON)
        group=masterdata.save(admin,'groups',None,{'name':'Ohne Freitext','active':True,'members':[]})
        masterdata.grant(admin,group,'AUTHOR',self.dep,'','')
        grant=s.query('SELECT id FROM role_assignments WHERE group_id=%s',[group])[0]['id']
        masterdata.revoke(admin,group,grant,'')
        notifications.save_notification_policy(self.reviewer,False,7,'')
        self.assertEqual(notifications.load_config()['reminder_days'],7)

    def test_revision_edit_review_and_withdrawal_allow_blank_explanation(self):
        s.transition(self.author,self.vid,'submit','Einreichen')
        decide(self.reviewer,self.vid,True,'Freigeben')
        self.enable_runtime_role()
        s.record_review(self.reviewer,self.vid,'UNCHANGED','')
        self.assertEqual(s.query('SELECT rationale FROM periodic_reviews WHERE version_id=%s',[self.vid])[0]['rationale'],DEFAULT_REASON)
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(f'/versions/{self.vid}/revision/',{'kind':'minor'}).status_code,302)
        revision=s.query("SELECT id FROM document_versions WHERE document_id=(SELECT document_id FROM document_versions WHERE id=%s) AND status='DRAFT'",[self.vid])[0]['id']
        original=s.get_version(self.author,revision)[1]
        s.edit_draft(self.author,revision,{'title':'Ohne Erläuterung','effective_from':original['effective_from'],'change_summary':''})
        self.assertEqual(s.get_version(self.author,revision)[1]['change_summary'],DEFAULT_REASON)
        s.lifecycle_action(self.reviewer,self.vid,'withdraw','',True)
        self.assertIsNone(s.query('SELECT current_release(%s) AS id',[original['document_id']])[0]['id'])
