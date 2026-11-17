from django.test import SimpleTestCase
from django import forms
from .form_ui import AppForm
from .account_forms import CreateAccountForm
from .auth_views import DMSAuthenticationForm


class FormUITests(SimpleTestCase):
    def test_required_optional_disabled_and_hidden_fields_are_distinguished(self):
        class Example(AppForm):
            title=forms.CharField(label='Titel')
            reason=forms.CharField(label='Begründung',required=False)
            fixed=forms.CharField(label='Fest',disabled=True,initial='fix')
            internal=forms.CharField(widget=forms.HiddenInput)
        form=Example()
        self.assertIn('required-marker',str(form['title'].label_tag()))
        for name in ['reason','fixed','internal']:
            self.assertNotIn('required-marker',str(form[name].label_tag()))
        self.assertIn('Pflichtfeld',form.as_p())
        self.assertTrue(form.fields['title'].required)
        self.assertFalse(form.fields['reason'].required)

    def test_account_and_login_share_required_markers(self):
        for form in (CreateAccountForm(),DMSAuthenticationForm()):
            html=form.as_p()
            self.assertIn('required-marker',html)
            self.assertIn('Pflichtfeld',html)
        self.assertNotIn('required-marker',str(CreateAccountForm()['reason'].label_tag()))
