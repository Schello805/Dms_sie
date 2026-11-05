from django import forms
from .services import query,actor

class DistributionForm(forms.Form):
    change_kind = forms.ChoiceField(label='Art der Änderung',choices=[('SUBSTANTIAL','Fachlich wesentlich'),('EDITORIAL','Redaktionell')])
    requires_ack = forms.BooleanField(label='Versionsbezogene Kenntnisnahme erforderlich',required=False)
    ack_days = forms.IntegerField(label='Kenntnisnahme innerhalb von Tagen',min_value=1,max_value=3650,initial=30)
    keywords = forms.CharField(label='Schlagwörter und alternative Suchbegriffe',required=False,max_length=2000)
    audiences = forms.TypedMultipleChoiceField(label='Zielgruppen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple,
        help_text='Ohne Zielgruppe gilt der Abteilungsgeltungsbereich. Zielgruppen vergeben keine Zugriffsrechte.')
    reason = forms.CharField(label='Begründung',max_length=4000,widget=forms.Textarea)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['audiences'].choices = [(g['id'],g['name']) for g in query('SELECT id,name FROM audience_groups WHERE active ORDER BY name')]

class AudienceForm(forms.Form):
    name = forms.CharField(label='Zielgruppe',max_length=200)
    description = forms.CharField(label='Beschreibung',required=False,max_length=2000,widget=forms.Textarea)
    reason = forms.CharField(label='Begründung',max_length=4000)

class WorkplaceForm(forms.Form):
    user_id = forms.TypedChoiceField(label='Mitarbeiter',coerce=int)
    department = forms.TypedChoiceField(label='Arbeitsplatz-Abteilung',coerce=int,empty_value=None,required=False)
    site = forms.CharField(label='Standort',max_length=200,required=False)
    activity = forms.CharField(label='Tätigkeit / Arbeitsplatz',max_length=200,required=False)
    audiences = forms.TypedMultipleChoiceField(label='Zielgruppen',coerce=int,required=False,widget=forms.CheckboxSelectMultiple)
    reason = forms.CharField(label='Begründung',max_length=4000)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['user_id'].choices = [(u['id'],u['display_name']) for u in query('SELECT id,display_name FROM users WHERE active ORDER BY display_name')]
        self.fields['department'].choices = [('', 'Nicht zugeordnet')]+[(d['id'],d['name']) for d in query('SELECT id,name FROM departments ORDER BY name')]
        self.fields['audiences'].choices = [(g['id'],g['name']) for g in query('SELECT id,name FROM audience_groups WHERE active ORDER BY name')]

class EvidenceForm(forms.Form):
    number = forms.CharField(label='Nachweisnummer',max_length=100)
    title = forms.CharField(label='Titel',max_length=400)
    category_id = forms.TypedChoiceField(label='Kategorie',coerce=int)
    department_id = forms.TypedChoiceField(label='Verantwortliche Abteilung',coerce=int)
    occurred_on = forms.DateField(label='Nachweisdatum',widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    retain_until = forms.DateField(label='Aufbewahren bis einschließlich',required=False,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'),help_text='Leer: Kategoriefrist ab Nachweisdatum; ist keine festgelegt, ist ein Datum erforderlich.')
    classification = forms.ChoiceField(label='Vertraulichkeit',choices=[('INTERNAL','Intern, berechtigte Leser'),('CONFIDENTIAL','Vertraulich, Ersteller und QMB'),('RESTRICTED','Streng vertraulich, Ersteller und QMB')])
    source_version_id = forms.TypedChoiceField(label='Bezug zur Dokumentfassung',coerce=int,empty_value=None,required=False)
    reason = forms.CharField(label='Beschreibung / Anlass',max_length=4000,widget=forms.Textarea)
    file = forms.FileField(label='Unveränderliche Nachweisdatei (max. 25 MiB)')
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        uid = actor(user)
        self.fields['source_version_id'].choices = [('', 'Kein Dokumentbezug')]+[(v['id'],f"{v['number']} · Version {v['major']}.{v['minor']} · {v['title']}") for v in query('SELECT v.id,d.number,v.major,v.minor,v.title FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE can_read_version(%s,v.id) ORDER BY d.number,v.major DESC,v.minor DESC LIMIT 2000',[uid])]
        self.fields['category_id'].choices = [(c['id'],c['name']) for c in query('SELECT id,name FROM document_categories ORDER BY name')]
        self.fields['department_id'].choices = [(d['id'],d['name']) for d in query("SELECT id,name FROM departments d WHERE has_role(%s,'AUTHOR',d.id,NULL) ORDER BY name",[uid])]

class RetentionForm(forms.Form):
    retain_until = forms.DateField(label='Aufbewahren bis einschließlich',widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    legal_hold = forms.BooleanField(label='Aussonderungssperre aktiv',required=False)
    reason = forms.CharField(label='Begründung der Aufbewahrungsentscheidung',max_length=4000,widget=forms.Textarea)

class AuditFilterForm(forms.Form):
    document_number = forms.CharField(label='Dokumentnummer (optional)',required=False,max_length=100)
    since = forms.DateField(label='Von',required=False,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    until = forms.DateField(label='Bis einschließlich',required=False,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    action = forms.CharField(label='Aktion (optional)',required=False,max_length=100)
    def clean(self):
        data = super().clean()
        if data.get('since') and data.get('until') and data['since']>data['until']:
            raise forms.ValidationError('Das Enddatum muss nach dem Startdatum liegen.')
        return data
