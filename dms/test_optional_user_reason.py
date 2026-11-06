from django.contrib.auth import get_user_model
from django.test import TestCase
from . import tests as fixtures, services as s
from . import test_improvements as improvements
from .account_forms import CreateAccountForm, PasswordForm, AccountStatusForm
from .forms import UserRolesForm, ContactEmailForm
from .master_forms import ProfileForm, MasterForm


class OptionalUserReasonTests(TestCase):
    setUp = fixtures.WorkflowTests.setUp
    admin = improvements.ImprovementTests.admin
    enable_runtime_role = fixtures.WorkflowTests.enable_runtime_role

    def test_user_and_master_data_forms_allow_optional_reason(self):
        for form in (CreateAccountForm(), PasswordForm(), AccountStatusForm(), UserRolesForm(), ContactEmailForm(), ProfileForm()):
            self.assertFalse(form.fields['reason'].required)
            self.assertIn('optional',form.fields['reason'].label)
        self.assertFalse(MasterForm(kind='departments').fields['reason'].required)

    def test_full_user_lifecycle_without_explanation_remains_audited(self):
        admin=self.admin();self.enable_runtime_role();self.client.force_login(admin)
        password='Initial-Optional-User-Password-2026!'
        response=self.client.post('/settings/users/new/',{'username':'optional-reader','display_name':'Optional Reader','email':'optional@example.test','password1':password,'password2':password})
        self.assertEqual(response.status_code,302)
        user=get_user_model().objects.get(username='optional-reader');uid=s.actor(user)
        response=self.client.post('/settings/users/',{'user_id':uid,'author':'on'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(s.allowed(uid,self.dep,'AUTHOR'))
        response=self.client.post(f'/settings/users/{uid}/profile/',{'display_name':'Optional Updated','email':'updated@example.test'})
        self.assertEqual(response.status_code,302)
        new='Reset-Optional-User-Password-2026!'
        response=self.client.post(f'/settings/users/{uid}/password/',{'password1':new,'password2':new})
        self.assertEqual(response.status_code,302)
        self.assertTrue(get_user_model().objects.get(pk=user.pk).check_password(new))
        for enabled in ('0','1'):
            self.assertEqual(self.client.post('/settings/users/status/',{'user_id':uid,'enabled':enabled}).status_code,302)
            self.assertEqual(get_user_model().objects.get(pk=user.pk).is_active,enabled=='1')
        self.client.force_login(get_user_model().objects.get(pk=user.pk))
        own='Own-Optional-User-Password-2026!'
        self.assertEqual(self.client.post('/account/password/',{'old_password':new,'password1':own,'password2':own}).status_code,302)
        self.assertTrue(get_user_model().objects.get(pk=user.pk).check_password(own))
        events=s.query("SELECT actor_id,reason,details FROM audit_events WHERE object_type='user' AND object_id=%s",[str(uid)])
        self.assertEqual(len(events),7)
        self.assertTrue(all(event['actor_id'] and event['reason']=='Keine zusätzliche Begründung angegeben.' for event in events))
        self.assertNotIn(password,str(events));self.assertNotIn(new,str(events));self.assertNotIn(own,str(events))
