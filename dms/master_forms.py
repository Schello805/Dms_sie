from django import forms
from . import services as s
from .masterdata import definition_locked


class MasterForm(forms.Form):
    name=forms.CharField(label='Bezeichnung',max_length=200)
    active=forms.BooleanField(label='Aktiv · für neue Zuordnungen verfügbar',initial=True,required=False)
    reason=forms.CharField(label='Begründung',max_length=4000,widget=forms.Textarea)

    def __init__(self,*args,kind,record=None,**kwargs):
        super().__init__(*args,**kwargs)
        record=record or {};self.locked=False
        if kind=='categories':
            self.fields['review_interval_months']=forms.IntegerField(label='Gültigkeit (Monate)',min_value=1,max_value=1200,initial=24)
            self.fields['retention_months']=forms.IntegerField(label='Aufbewahrung (Monate)',min_value=1,max_value=1200,required=False)
            rows=s.query('SELECT id,name,active FROM storage_locations WHERE active OR id=%s ORDER BY name',[record.get('storage_location_id')])
            self.fields['storage_location_id']=forms.TypedChoiceField(label='Aufbewahrungsort',coerce=int,choices=[('','Bitte auswählen')]+[(r['id'],r['name']+(' (deaktiviert)' if not r['active'] else '')) for r in rows])
        elif kind=='departments':
            self.fields['code']=forms.RegexField(r'^[A-Za-z0-9_.-]+$',label='Kürzel',max_length=50)
            rows=s.query('WITH RECURSIVE invalid AS (SELECT id FROM departments WHERE id=%s UNION SELECT d.id FROM departments d JOIN invalid p ON d.parent_id=p.id) SELECT id,name,active FROM departments WHERE id NOT IN (SELECT id FROM invalid) AND (active OR id=%s) ORDER BY name',[record.get('id'),record.get('parent_id')])
            self.fields['parent_id']=forms.TypedChoiceField(label='Übergeordnete Abteilung',coerce=int,required=False,empty_value=None,choices=[('','Keine')]+[(r['id'],r['name']+(' (deaktiviert)' if not r['active'] else '')) for r in rows])
        elif kind=='locations':
            self.fields['description']=forms.CharField(label='Beschreibung',max_length=2000,required=False,widget=forms.Textarea)
        elif kind=='standards':
            self.fields['edition']=forms.CharField(label='Ausgabe',max_length=50)
        elif kind=='references':
            self.fields.pop('name')
            rows=s.query('SELECT id,name,edition,active FROM standards WHERE active OR id=%s ORDER BY name,edition',[record.get('standard_id')])
            self.fields['standard_id']=forms.TypedChoiceField(label='Normausgabe',coerce=int,choices=[('','Bitte auswählen')]+[(r['id'],r['name']+' · '+r['edition']+(' (deaktiviert)' if not r['active'] else '')) for r in rows])
            self.fields['reference']=forms.CharField(label='Referenz / Kapitel',max_length=100)
            self.fields['label']=forms.CharField(label='Kurzbezeichnung',max_length=500)
        elif kind=='groups':
            self.fields['active'].label='Aktiv · Gruppenberechtigungen sind wirksam'
            self.fields['active'].help_text='Deaktivieren entzieht die Gruppenrechte sofort. Mitgliedschaften und direkte Benutzerrechte bleiben erhalten.'
            rows=s.query('''SELECT u.id,u.display_name,a.username,u.active AND a.is_active AS active FROM users u JOIN auth_user a ON a.id=u.auth_user_id
                WHERE (u.active AND a.is_active) OR EXISTS(SELECT 1 FROM group_memberships WHERE group_id=%s AND user_id=u.id) ORDER BY u.display_name,u.id''',[record.get('id')])
            self.fields['members']=forms.TypedMultipleChoiceField(label='Mitglieder',coerce=int,required=False,choices=[(r['id'],r['display_name']+' (@'+r['username']+')'+(' (deaktiviert)' if not r['active'] else '')) for r in rows],widget=forms.SelectMultiple(attrs={'size':12,'data-filter-options':'true'}),help_text='Mehrere Einträge auswählen. Bestehende deaktivierte Konten können beibehalten oder entfernt werden.')
        if kind=='groups' and record.get('id') and s.query("SELECT 1 FROM role_assignments WHERE group_id=%s AND role NOT IN ('READER','AUTHOR') LIMIT 1",[record['id']]):
            self.initial['active']=record['active']
            self.initial['members']=record['members']
            self.fields['members'].disabled=True
            self.fields['active'].disabled=True
            self.fields['members'].help_text='Diese Gruppe enthält geschützte Altberechtigungen. Mitglieder und Status über die administrative CLI prüfen.'
        if record.get('id') and definition_locked(kind,record['id']):
            self.locked=True
            for field in (('name','edition') if kind=='standards' else ('standard_id','reference','label')):
                self.fields[field].disabled=True
        # Identity and business fields first; explicit status/reason confirmation last.
        self.order_fields([name for name in self.fields if name not in ('active','reason')]+['active','reason'])


class GroupGrantForm(forms.Form):
    role=forms.ChoiceField(label='Rolle',choices=[('READER','Leser'),('AUTHOR','Autor')])
    department_id=forms.TypedChoiceField(label='Abteilung',coerce=int,empty_value=None,required=False)
    document_number=forms.CharField(label='Oder Dokumentnummer',max_length=100,required=False,help_text='Leer lassen für alle Dokumente im gewählten Bereich. Dokumentinhalte werden hier nicht angezeigt.')
    reason=forms.CharField(label='Begründung',max_length=4000)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['department_id'].choices=[('','Unternehmensweit')]+[(r['id'],r['name']) for r in s.query('SELECT id,name FROM departments WHERE active ORDER BY name')]
    def clean(self):
        data=super().clean()
        if data.get('department_id') and data.get('document_number'):
            raise forms.ValidationError('Abteilung oder Dokumentnummer wählen, nicht beides.')
        return data


class ProfileForm(forms.Form):
    display_name=forms.CharField(label='Anzeigename',max_length=300)
    email=forms.EmailField(label='E-Mail',required=False,max_length=254)
    reason=forms.CharField(label='Begründung (optional)',required=False,max_length=4000,widget=forms.Textarea)
