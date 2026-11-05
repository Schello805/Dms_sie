from django import forms


class CreateAccountForm(forms.Form):
    username = forms.RegexField(r'^[a-zA-Z0-9_.@+-]{1,150}$',label='Benutzername',max_length=150)
    display_name = forms.CharField(label='Anzeigename',max_length=300)
    email = forms.EmailField(label='E-Mail',required=False,max_length=254)
    password1 = forms.CharField(label='Initiales Passwort',max_length=1024,strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    password2 = forms.CharField(label='Passwort wiederholen',max_length=1024,strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    reason = forms.CharField(label='Begründung',max_length=4000)


class PasswordForm(forms.Form):
    old_password = forms.CharField(label='Aktuelles Passwort',required=False,max_length=1024,strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}))
    password1 = forms.CharField(label='Neues Passwort',max_length=1024,strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    password2 = forms.CharField(label='Passwort wiederholen',max_length=1024,strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    reason = forms.CharField(label='Begründung',max_length=4000,initial='Eigenes Passwort ändern')


class AccountStatusForm(forms.Form):
    user_id = forms.IntegerField(min_value=1)
    enabled = forms.TypedChoiceField(choices=[('1','Aktivieren'),('0','Deaktivieren')],coerce=lambda value:value=='1')
    reason = forms.CharField(max_length=4000)
