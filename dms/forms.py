from django import forms
from .services import actor, query

class MappingFieldsMixin:
    def load_mapping_choices(self):
        rows = query('SELECT id,name FROM departments ORDER BY name')
        self.fields['applicable_departments'].choices = [(r['id'],r['name']) for r in rows]
        rows = query('''SELECT r.id,s.name,s.edition,r.reference,r.label FROM standard_references r
            JOIN standards s ON s.id=r.standard_id ORDER BY s.name,s.edition,r.reference''')
        self.fields['standard_references'].choices = [(r['id'],f"{r['name']} · {r['edition']} · {r['reference']} — {r['label']}") for r in rows]

class DocumentForm(MappingFieldsMixin, forms.Form):
    number = forms.CharField(label='Dokumentnummer', max_length=100)
    title = forms.CharField(label='Titel', max_length=300)
    document_type = forms.ChoiceField(label='Kategorie', choices=[(x,x) for x in ['Richtlinie','Prozess','Arbeitsanweisung','Betriebsanweisung','Vorlage','Externe Norm']])
    department = forms.TypedChoiceField(label='Verantwortliche Abteilung', coerce=int)
    change_summary = forms.CharField(label='Änderungsbeschreibung', widget=forms.Textarea)
    effective_from = forms.DateTimeField(label='Erstmalig gültig ab', widget=forms.DateTimeInput(attrs={'type':'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    classification = forms.ChoiceField(label='Klassifizierung',choices=[('PUBLIC','Öffentlich (Metadaten auch ohne Anmeldung)'),('INTERNAL','Intern'),('CONFIDENTIAL','Vertraulich'),('RESTRICTED','Streng vertraulich')],initial='INTERNAL',help_text='Öffentliche Metadaten können ohne Anmeldung sichtbar sein. Dateien erfordern eine Anmeldung. Vertrauliche Fassungen benötigen zusätzlich eine ausdrückliche Zugriffsfreigabe.')
    applicable_departments = forms.TypedMultipleChoiceField(label='Geltungsbereich: Abteilungen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple)
    standard_references = forms.TypedMultipleChoiceField(label='Normzuordnungen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple)


    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        uid = actor(user)
        rows = query("SELECT d.id,d.name FROM departments d WHERE EXISTS (SELECT 1 FROM effective_role_assignments r WHERE r.user_id=%s AND r.role='AUTHOR' AND r.document_id IS NULL AND (r.department_id IS NULL OR r.department_id=d.id)) ORDER BY d.name", [uid])
        self.fields['document_type'].choices = [('', 'Bitte Kategorie auswählen')]+[(r['name'],r['name']) for r in query('SELECT name FROM document_categories ORDER BY name')]
        self.fields['department'].choices = [('', 'Bitte Abteilung auswählen')]+[(r['id'],r['name']) for r in rows]
        self.load_mapping_choices()

class ActionForm(forms.Form):
    action = forms.ChoiceField(choices=[('submit','Einreichen'),('accept','Zustimmen'),('return','Zurückgeben'),('approve','Freigeben'),('reject','Ablehnen')])
    comment = forms.CharField(label='Bemerkung',required=False,max_length=4000,widget=forms.Textarea)

class EditForm(MappingFieldsMixin, forms.Form):
    title = forms.CharField(label='Titel', max_length=300)
    change_summary = forms.CharField(label='Änderungsbeschreibung', widget=forms.Textarea)
    effective_from = forms.DateTimeField(label='Erstmalig gültig ab', widget=forms.DateTimeInput(attrs={'type':'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    classification = forms.ChoiceField(label='Klassifizierung',choices=[('PUBLIC','Öffentlich (Metadaten auch ohne Anmeldung)'),('INTERNAL','Intern'),('CONFIDENTIAL','Vertraulich'),('RESTRICTED','Streng vertraulich')],initial='INTERNAL',help_text='Öffentliche Metadaten können ohne Anmeldung sichtbar sein. Dateien erfordern eine Anmeldung. Vertrauliche Fassungen benötigen zusätzlich eine ausdrückliche Zugriffsfreigabe.')
    applicable_departments = forms.TypedMultipleChoiceField(label='Geltungsbereich: Abteilungen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple)
    standard_references = forms.TypedMultipleChoiceField(label='Normzuordnungen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple)


    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.load_mapping_choices()

class UploadForm(forms.Form):
    file = forms.FileField(label='Dokumentdatei (maximal 25 MiB)')

class ReviewForm(forms.Form):
    result = forms.ChoiceField(label='Prüfergebnis',choices=[('','Bitte Prüfergebnis auswählen'),('UNCHANGED','Weiterhin geeignet'),('REVISION_REQUIRED','Überarbeitung erforderlich'),('WITHDRAWAL_REQUIRED','Rückzug erforderlich')])
    rationale = forms.CharField(label='Prüfbegründung',max_length=4000,widget=forms.Textarea)
    # Successful reviews receive the configured category interval automatically.

class RevisionForm(forms.Form):
    kind = forms.ChoiceField(label='Versionssprung',choices=[('minor','Minor: ergänzende Änderung (z. B. 1.0 → 1.1)'),('major','Major: grundlegende Änderung (z. B. 1.1 → 2.0)')],initial='minor')
    reason = forms.CharField(label='Grund der Überarbeitung',max_length=4000,widget=forms.Textarea)


class AccessForm(forms.Form):
    access_mode = forms.ChoiceField(label='Zugriffsbereich',choices=[('DEPARTMENT','Abteilungs- und Dokumentrollen'),('EXPLICIT','Zusätzlich nur ausdrücklich freigegebene Personen/Gruppen')])
    users = forms.TypedMultipleChoiceField(label='Ausdrücklich berechtigte Personen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple)
    groups = forms.TypedMultipleChoiceField(label='Ausdrücklich berechtigte Gruppen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple)
    reason = forms.CharField(label='Grund der Berechtigungsänderung',max_length=4000,widget=forms.Textarea)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['users'].choices = [(r['id'],r['display_name']) for r in query('SELECT u.id,u.display_name FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.active AND a.is_active ORDER BY u.display_name,u.id')]
        self.fields['groups'].choices = [(r['id'],r['name']) for r in query('SELECT id,name FROM dms_groups WHERE active ORDER BY name')]

class LifecycleForm(forms.Form):
    action = forms.ChoiceField(label='Vorgang',choices=[('withdraw','Dokument mit allen vorab freigegebenen Fassungen sofort zurückziehen'),('archive','Diese Fassung archivieren')])
    reason = forms.CharField(label='Begründung',max_length=4000,widget=forms.Textarea)
    confirmed = forms.BooleanField(label='Ich bestätige die Auswirkung auf die Verfügbarkeit für Leser.')


class CategorySettingsForm(forms.Form):
    reason = forms.CharField(label='Grund der Änderung',max_length=4000,widget=forms.Textarea)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.categories = query('SELECT id,name,review_interval_months,retention_months,storage_location_id FROM document_categories ORDER BY name')
        places = [(r['id'],r['name']) for r in query('SELECT id,name FROM storage_locations WHERE active ORDER BY name')]
        for category in self.categories:
            self.fields[f"category_{category['id']}"] = forms.IntegerField(label=category['name'],min_value=1,max_value=1200,initial=category['review_interval_months'],widget=forms.NumberInput(attrs={'min':1,'max':1200}))
            self.fields[f"retention_{category['id']}"] = forms.IntegerField(label='Aufbewahrung (Monate)',required=False,min_value=1,max_value=1200,initial=category['retention_months'])
            self.fields[f"location_{category['id']}"] = forms.TypedChoiceField(label='Aufbewahrungsort',coerce=int,choices=places,initial=category['storage_location_id'])
    def intervals(self):
        return {c['id']:self.cleaned_data[f"category_{c['id']}"] for c in self.categories}
    def retention(self):
        return {c['id']:self.cleaned_data[f"retention_{c['id']}"] for c in self.categories}
    def locations(self):
        return {c['id']:self.cleaned_data[f"location_{c['id']}"] for c in self.categories}
    def rows(self):
        return [{'name':c['name'],'validity':self[f"category_{c['id']}"],'retention':self[f"retention_{c['id']}"],'location':self[f"location_{c['id']}"]} for c in self.categories]


class SMTPSettingsForm(forms.Form):
    enabled = forms.BooleanField(label='Automatische E-Mail-Erinnerungen aktivieren',required=False)
    reminder_days = forms.IntegerField(label='Tage vor Ablauf erinnern',min_value=0,max_value=3650,initial=30,help_text='0 = nur bei Fälligkeit. Je Prüftermin höchstens eine Vorab- und eine Fälligkeitsmeldung.')
    smtp_host = forms.CharField(label='SMTP-Server',max_length=253,required=False)
    smtp_port = forms.IntegerField(label='SMTP-Port',min_value=1,max_value=65535,initial=587)
    smtp_security = forms.ChoiceField(label='SMTP-Verschlüsselung',choices=[('STARTTLS','STARTTLS'),('SSL','TLS/SSL'),('NONE','Keine (interner Relay)')])
    smtp_username = forms.CharField(label='SMTP-Benutzername',max_length=254,required=False)
    password = forms.CharField(label='SMTP-Passwort',max_length=2000,required=False,strip=False,widget=forms.PasswordInput(render_value=False,attrs={'autocomplete':'new-password'}),help_text='Leer lassen, um das gespeicherte Passwort beizubehalten.')
    clear_password = forms.BooleanField(label='Gespeichertes SMTP-Passwort entfernen',required=False)
    sender_email = forms.EmailField(label='Absenderadresse',required=False)
    base_url = forms.URLField(label='DMS-Adresse für Links in E-Mails',required=False,help_text='Zum Beispiel http://192.168.1.191:8000')
    reason = forms.CharField(label='Grund der Änderung',max_length=4000,widget=forms.Textarea)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields.pop('enabled')
        self.fields.pop('reminder_days')

class SMTPTestForm(forms.Form):
    recipient = forms.EmailField(label='Empfänger der Test-E-Mail')

class ContactEmailForm(forms.Form):
    user_id = forms.IntegerField(min_value=1)
    email = forms.EmailField(required=False)
    reason = forms.CharField(max_length=4000)


class QMBTeamForm(forms.Form):
    primary_id = forms.TypedChoiceField(label='QMB',coerce=int,empty_value=None,required=False)
    lead_id = forms.TypedChoiceField(label='Leitung der QMB-Abteilung (zusätzliche Freigabe)',coerce=int,empty_value=None,required=False,help_text='Darf nach unabhängiger QMB-Prüfung freigeben. Keine QMB-Prüf- oder Verwaltungsrechte; keine Selbstfreigabe.')
    deputy_id = forms.TypedChoiceField(label='QMB-Vertretung',coerce=int,empty_value=None,required=False)
    reason = forms.CharField(label='Grund der Änderung',max_length=4000,widget=forms.Textarea)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        people = [('', 'Nicht zugewiesen')]+[(u['id'],u['display_name']) for u in query('SELECT u.id,u.display_name FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.active AND a.is_active ORDER BY u.display_name')]
        self.fields['primary_id'].choices = people
        self.fields['deputy_id'].choices = people
        self.fields['lead_id'].choices = people

class StorageLocationForm(forms.Form):
    name = forms.CharField(label='Aufbewahrungsort',max_length=200)
    description = forms.CharField(label='Beschreibung',required=False,max_length=2000,widget=forms.Textarea)
    reason = forms.CharField(label='Grund der Anlage',max_length=4000)


class ReminderPolicyForm(forms.Form):
    enabled = forms.BooleanField(label='Automatische Review-Erinnerungen aktivieren',required=False)
    reminder_days = forms.IntegerField(label='Tage vor Ablauf erinnern',min_value=0,max_value=3650)
    reason = forms.CharField(label='Grund der Änderung',max_length=4000,widget=forms.Textarea)

class BrandingForm(forms.Form):
    logo = forms.FileField(label='Neues Hauptlogo',help_text='PNG, JPEG oder WebP, maximal 5 MiB, 64–4096 Pixel je Seite. Favicons werden automatisch erzeugt.',widget=forms.ClearableFileInput(attrs={'accept':'image/png,image/jpeg,image/webp'}))
    reason = forms.CharField(label='Begründung für den Logowechsel',max_length=4000,widget=forms.Textarea)

class DocumentUploadForm(DocumentForm):
    file = forms.FileField(label='Dokumentdatei (max. 25 MiB)')
    intent = forms.ChoiceField(label='Nach dem Upload',choices=[('draft','Als Entwurf speichern'),('submit','Freigabe durch QMB anfordern')])
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from django.utils import timezone
        self.fields['effective_from'].label = 'Erstmalig gültig ab'
        self.fields['effective_from'].required = False
        self.fields['effective_from'].initial = None
        self.fields['effective_from'].help_text = 'Leer lassen: tatsächlicher Uploadzeitpunkt. Im Entwurf nachträglich änderbar.'
        self.fields['change_summary'].required = False
        self.fields['change_summary'].initial = 'Erstupload'
        self.fields['file'].widget.attrs['accept'] = '.pdf,.docx,.xlsx,.odt,.txt'
        self.fields['file'].help_text = 'PDF und TXT können direkt angesehen werden. Für Office-Dateien kannst du im Entwurf zusätzlich eine PDF-Lesefassung hinterlegen.'
        self.fields['applicable_departments'].help_text = 'Die verantwortliche Abteilung ist automatisch enthalten.'
    def clean_effective_from(self):
        from django.utils import timezone
        return self.cleaned_data.get('effective_from') or timezone.now()
    def clean_change_summary(self):
        return self.cleaned_data.get('change_summary') or 'Erstupload'

class UserRolesForm(forms.Form):
    user_id = forms.IntegerField(min_value=1,widget=forms.HiddenInput)
    author = forms.BooleanField(label='Autor',required=False)
    qmb = forms.BooleanField(label='QMB',required=False)
    admin = forms.BooleanField(label='Admin (IT)',required=False)
    reason = forms.CharField(label='Begründung',max_length=4000)
