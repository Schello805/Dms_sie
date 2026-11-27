from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from . import processes, process_demo, demo_diagrams, services as s
from .form_ui import AppForm
from .audit_text import OptionalReasonField
from .policies import is_qmb, require_qmb


class ProcessForm(AppForm):
    code=forms.CharField(label='Prozesskennung',max_length=80)
    title=forms.CharField(label='Bezeichnung',max_length=300)
    owner_id=forms.TypedChoiceField(label='Prozessverantwortlicher',coerce=int)
    description=forms.CharField(label='Beschreibung',widget=forms.Textarea,required=False,max_length=20000,help_text='Für die Veröffentlichung erforderlich.')
    inputs=forms.CharField(label='Eingaben',required=False,max_length=5000,widget=forms.Textarea)
    outputs=forms.CharField(label='Ergebnisse',required=False,max_length=5000,widget=forms.Textarea)
    responsibilities=forms.CharField(label='Beteiligte Rollen und Zuständigkeiten',required=False,max_length=5000,widget=forms.Textarea)
    documents=forms.TypedMultipleChoiceField(label='Verknüpfte Dokumente',coerce=int,required=False,widget=forms.SelectMultiple)
    references=forms.TypedMultipleChoiceField(label='Normanforderungen',coerce=int,required=False,widget=forms.SelectMultiple)
    active=forms.BooleanField(label='Aktiv – Deaktivieren blendet auch alle untergeordneten Prozesse aus',initial=True,required=False)
    reason=OptionalReasonField(label='Grund der Änderung',max_length=4000)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['owner_id'].choices=[(u['id'],u['display_name']) for u in s.query('SELECT u.id,u.display_name FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.active AND a.is_active ORDER BY u.display_name')]
        self.fields['documents'].choices=[(d['id'],d['number']+' · '+d['title']) for d in s.query('SELECT d.id,d.number,v.title FROM documents d JOIN LATERAL (SELECT title FROM document_versions WHERE document_id=d.id ORDER BY major DESC,minor DESC LIMIT 1) v ON true ORDER BY d.number')]
        self.fields['references'].choices=[(r['id'],r['name']+' · '+r['reference']) for r in s.query('SELECT r.id,s.name,r.reference FROM standard_references r JOIN standards s ON s.id=r.standard_id ORDER BY s.name,r.reference')]


def landscape(request,target=None):
    from . import bpmn_views
    return bpmn_views.diagram(request,target)


@login_required
def edit(request,target=None):
    require_qmb(request.user)
    all_nodes={n['id']:n for n in processes.nodes(True,target)}
    current=all_nodes.get(target) if target else None
    if target and not current:raise Http404
    try:parent_id=current['parent_id'] if current else int(request.GET['parent']) if request.GET.get('parent') else None
    except ValueError:raise Http404
    parent=all_nodes.get(parent_id) if parent_id else None
    if parent_id and (not parent or parent['level']>=4):raise Http404
    initial={**current['draft'],'code':current['code'],'active':current['active']} if current else {'active':True}
    form=ProcessForm(request.POST or None,initial=initial)
    if current:form.fields['code'].disabled=True
    if request.method=='POST' and form.is_valid():
        data=dict(form.cleaned_data);code=data.pop('code');active=data.pop('active');reason=data.pop('reason')
        try:
            saved=processes.save(request.user,target,parent_id,code,data,request.POST.get('action')=='publish',active,reason)
        except ValidationError as error:form.add_error(None,error)
        else:
            messages.success(request,'Prozess veröffentlicht.' if request.POST.get('action')=='publish' else 'Arbeitsstand gespeichert. Die veröffentlichte Fassung bleibt erhalten.')
            return redirect('process_detail',target=saved)
    return render(request,'dms/process_edit.html',{'form':form,'current':current,'parent':parent,'level_label':processes.LEVELS[(parent['level']+1) if parent else 1]})


@login_required
def demo(request):
    require_qmb(request.user)
    if request.method!='POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    try:
        if request.POST.get('action')=='install':process_demo.install(request.user)
        elif request.POST.get('action')=='diagrams':
            count=demo_diagrams.ensure(request.user)
            messages.success(request,f'{count} fehlende Demo-Flussdiagramme ergänzt. Vorhandene Diagramme bleiben unverändert.')
            return redirect('processes')
        else:process_demo.toggle(request.user,request.POST.get('action')=='show')
    except ValidationError as error:
        messages.error(request,'Demo konnte nicht angelegt werden: '+ '; '.join(error.messages))
    else:messages.success(request,'Demo-Prozesse sind eingeblendet.' if process_demo.state()['visible'] else 'Demo-Prozesse sind für alle ausgeblendet. Die Daten bleiben erhalten.')
    return redirect('processes')
