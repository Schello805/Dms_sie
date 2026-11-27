from datetime import date
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from . import process_controls as domain, services as s
from .form_ui import AppForm
from .audit_text import OptionalReasonField
from .policies import require_qmb

STATUS = [('open','Offen'),('progress','In Umsetzung'),('closed','Abgeschlossen'),('accepted','Akzeptiert')]
SCALE = [(n,str(n)) for n in range(1,6)]


class ControlForm(AppForm):
    title = forms.CharField(label='Bezeichnung',max_length=300)
    owner_id = forms.TypedChoiceField(label='Verantwortlich',coerce=int)
    active = forms.BooleanField(label='Aktiv',initial=True,required=False)
    revision = forms.IntegerField(widget=forms.HiddenInput,min_value=0,initial=0)
    reason = OptionalReasonField(label='Grund der Änderung',max_length=4000)

    def __init__(self,*args,kind,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['owner_id'].choices = [(u['id'],u['display_name']) for u in s.query('SELECT u.id,u.display_name FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.active AND a.is_active ORDER BY u.display_name')]
        if kind == 'risk':
            self.fields.update({
                'description':forms.CharField(label='Ursache und mögliche Folgen',widget=forms.Textarea,max_length=5000),
                'probability':forms.TypedChoiceField(label='Eintrittswahrscheinlichkeit (1–5)',choices=SCALE,coerce=int),
                'impact':forms.TypedChoiceField(label='Auswirkung (1–5)',choices=SCALE,coerce=int),
                'action':forms.CharField(label='Maßnahme',widget=forms.Textarea,required=False,max_length=5000),
                'due_on':forms.DateField(label='Maßnahme fällig am',required=False,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d')),
                'status':forms.ChoiceField(label='Bearbeitungsstand',choices=STATUS),
                'residual_probability':forms.TypedChoiceField(label='Verbleibende Wahrscheinlichkeit',required=False,choices=[('','Noch nicht bewertet')]+SCALE,coerce=int,empty_value=None),
                'residual_impact':forms.TypedChoiceField(label='Verbleibende Auswirkung',required=False,choices=[('','Noch nicht bewertet')]+SCALE,coerce=int,empty_value=None),
                'effectiveness':forms.CharField(label='Wirksamkeitsnachweis / Begründung der Akzeptanz',required=False,widget=forms.Textarea,max_length=5000),
            })
        else:
            self.fields.update({
                'description':forms.CharField(label='Definition und Berechnung',widget=forms.Textarea,max_length=5000),
                'source':forms.CharField(label='Datenquelle',max_length=500),
                'unit':forms.CharField(label='Einheit',max_length=40,help_text='Zum Beispiel %, kWh/Stück oder Tage.'),
                'direction':forms.ChoiceField(label='Zielrichtung',choices=[('gte','Mindestens (≥)'),('lte','Höchstens (≤)')]),
                'target':forms.DecimalField(label='Zielwert',max_digits=20,decimal_places=6),
                'interval_months':forms.IntegerField(label='Messrhythmus in Monaten',min_value=1,max_value=120,initial=1),
                'first_due':forms.DateField(label='Erste Messung fällig am',widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'),initial=date.today),
            })
        self.order_fields([key for key in self.fields if key not in ('active','revision','reason')]+['active','revision','reason'])

    def clean(self):
        data = super().clean()
        if 'probability' in self.fields:
            if bool(data.get('residual_probability')) != bool(data.get('residual_impact')):
                self.add_error('residual_impact','Beide Werte für die Restbewertung angeben.')
            if data.get('status') in ('closed','accepted') and not data.get('effectiveness'):
                self.add_error('effectiveness','Für Abschluss oder Akzeptanz einen Nachweis bzw. eine Begründung angeben.')
            if data.get('status') == 'progress' and (not data.get('action') or not data.get('due_on')):
                self.add_error('action','Bei laufender Umsetzung Maßnahme und Fälligkeitsdatum angeben.')
        return data


class MeasurementForm(AppForm):
    measured_on = forms.DateField(label='Messdatum',initial=date.today,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    value = forms.DecimalField(label='Messwert',max_digits=20,decimal_places=6)
    note = forms.CharField(label='Notiz',required=False,max_length=4000,widget=forms.Textarea,help_text='Ein weiterer Wert am selben Datum korrigiert die Anzeige; der ursprüngliche Wert bleibt erhalten. Eine Notiz ist optional.')
    revision = forms.IntegerField(widget=forms.HiddenInput,min_value=1)

    def clean_measured_on(self):
        day = self.cleaned_data['measured_on']
        if day > date.today():raise ValidationError('Das Messdatum darf nicht in der Zukunft liegen.')
        return day


def get_process(target):
    rows = s.query("SELECT id,code,coalesce(live->>'title',draft->>'title') AS title,active FROM ims_processes WHERE id=%s",[target])
    if not rows:raise Http404
    return rows[0]


@login_required
def overview(request,target):
    require_qmb(request.user)
    process = get_process(target)
    items = domain.controls(request.user,target)
    for item in items:
        if item['kind']=='risk':item['status_label']=dict(STATUS)[item['data']['status']]
    return render(request,'dms/process_controls.html',{'process':process,'risks':[i for i in items if i['kind']=='risk'],'kpis':[i for i in items if i['kind']=='kpi']})


@login_required
def edit(request,target,kind,control=None):
    require_qmb(request.user)
    process = get_process(target)
    if kind not in ('risk','kpi'):raise Http404
    item = next((i for i in domain.controls(request.user,target) if i['id']==control and i['kind']==kind),None)
    if control and item is None:raise Http404
    initial = {**item['data'],'active':item['active'],'revision':item['revision']} if item else {'active':True,'revision':0}
    form = ControlForm(request.POST or None,initial=initial,kind=kind)
    if request.method=='POST' and form.is_valid():
        data = dict(form.cleaned_data)
        active = data.pop('active');expected = data.pop('revision');reason = data.pop('reason')
        data = {k:(v.isoformat() if hasattr(v,'isoformat') else str(v) if k=='target' else v) for k,v in data.items()}
        try:domain.save(request.user,target,control,kind,data,active,expected,reason)
        except ValidationError as error:form.add_error(None,error)
        else:
            messages.success(request,'Risiko gespeichert.' if kind=='risk' else 'Kennzahl gespeichert.')
            return redirect('process_controls',target=target)
    history = s.query('SELECT h.*,u.display_name FROM process_control_history h JOIN users u ON u.id=h.actor_id WHERE control_id=%s ORDER BY revision DESC',[control]) if item else []
    for revision in history:
        data=domain.decode(revision['payload'])
        revision['fields']=[]
        for key,value in data.items():
            field=form.fields.get(key)
            if not field:continue
            if key=='owner_id':
                owner=s.query('SELECT display_name FROM users WHERE id=%s',[value])
                value=owner[0]['display_name'] if owner else 'Nicht mehr zugeordnet'
            elif hasattr(field,'choices'):value=dict(field.choices).get(value,value)
            elif key in ('due_on','first_due') and value:value=date.fromisoformat(value).strftime('%d.%m.%Y')
            revision['fields'].append((field.label,value))
    return render(request,'dms/process_control_edit.html',{'process':process,'form':form,'kind':kind,'item':item,'history':history})


@login_required
def measurements(request,target,control):
    require_qmb(request.user)
    process = get_process(target)
    item = next((i for i in domain.controls(request.user,target) if i['id']==control and i['kind']=='kpi'),None)
    if item is None:raise Http404
    form = MeasurementForm(request.POST or None,initial={'revision':item['revision']})
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        try:domain.measure(request.user,control,data['measured_on'],data['value'],data['note'],data['revision'])
        except ValidationError as error:form.add_error(None,error)
        else:
            messages.success(request,'Messwert gespeichert. Frühere Einträge bleiben erhalten.')
            return redirect('process_measurements',target=target,control=control)
    rows = s.query('SELECT m.*,u.display_name FROM process_measurements m JOIN users u ON u.id=m.actor_id WHERE control_id=%s ORDER BY measured_on DESC,id DESC LIMIT 200',[control])
    seen=set()
    for row in rows:
        definition=domain.decode(row['definition']);row['unit']=definition['unit'];row['target']=definition['target'];row['direction']='≥' if definition['direction']=='gte' else '≤'
        row['superseded']=row['measured_on'] in seen;seen.add(row['measured_on'])
    return render(request,'dms/process_measurements.html',{'process':process,'item':item,'form':form,'measurements':rows})
