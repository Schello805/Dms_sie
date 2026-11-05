from django import forms

class DirectorySettingsForm(forms.Form):
    directory_type = forms.ChoiceField(label='Verzeichnistyp',choices=[('AD','Microsoft Active Directory'),('LDAP','LDAP-Verzeichnis')])
    domain = forms.CharField(label='AD-Domäne',max_length=253,required=False,help_text='Zum Beispiel firma.local; bei allgemeinem LDAP optional.')
    host = forms.CharField(label='Server / Domaincontroller',max_length=253,required=False,help_text='Hostname oder IP, ohne ldap://, Port oder Zugangsdaten.')
    port = forms.IntegerField(label='Port',min_value=1,max_value=65535,initial=636)
    security = forms.ChoiceField(label='Transportverschlüsselung',choices=[('LDAPS','LDAPS (typisch Port 636)'),('STARTTLS','LDAP mit StartTLS (typisch Port 389)')])
    timeout_seconds = forms.IntegerField(label='Verbindungszeitlimit in Sekunden',min_value=1,max_value=60,initial=5)
    base_dn = forms.CharField(label='Basis-DN',max_length=2000,required=False,help_text='Zum Beispiel DC=firma,DC=local.')
    bind_identity = forms.CharField(label='Bind-DN / Dienstkonto-UPN',max_length=2000,required=False,help_text='Zum Beispiel CN=DMS-Lesen,OU=Dienstkonten,DC=firma,DC=local oder dms-lesen@firma.local.')
    password = forms.CharField(label='Kennwort des Bind-Kontos',max_length=2000,required=False,strip=False,
        widget=forms.PasswordInput(render_value=False,attrs={'autocomplete':'new-password'}),help_text='Leer lassen, um das gespeicherte Kennwort beizubehalten.')
    clear_password = forms.BooleanField(label='Gespeichertes Bind-Kennwort entfernen',required=False)
    user_base_dn = forms.CharField(label='Benutzer-Suchbasis',max_length=2000,required=False,help_text='Leer = Basis-DN verwenden.')
    user_filter = forms.CharField(label='Benutzer-Suchfilter',max_length=2000,help_text='Genau einmal {username}; AD z. B. (sAMAccountName={username}), LDAP z. B. (uid={username}).')
    username_attribute = forms.CharField(label='Anmeldeattribut',max_length=200,help_text='AD: sAMAccountName oder userPrincipalName; LDAP häufig uid.')
    name_attribute = forms.CharField(label='Anzeigename-Attribut',max_length=200)
    email_attribute = forms.CharField(label='E-Mail-Attribut',max_length=200)
    identity_attribute = forms.CharField(label='Stabile externe Benutzerkennung',max_length=200,help_text='AD typischerweise objectGUID; LDAP zum Beispiel entryUUID.')
    group_base_dn = forms.CharField(label='Gruppen-Suchbasis',max_length=2000,required=False)
    group_filter = forms.CharField(label='Gruppen-Suchfilter',max_length=2000)
    membership_attribute = forms.CharField(label='Gruppenzugehörigkeits-Attribut',max_length=200,help_text='AD typischerweise memberOf.')
    reason = forms.CharField(label='Begründung der Konfigurationsänderung',max_length=4000,widget=forms.Textarea)
