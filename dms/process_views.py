from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from . import processes, services as s
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
    manager=is_qmb(request.user)
    all_nodes=processes.nodes(manager)
    by_id={row['id']:row for row in all_nodes}
    current=by_id.get(target) if target else None
    if target and not current:raise Http404
    crumbs=[by_id[i] for i in current['path'] if i in by_id] if current else []
    search=request.GET.get('q','').strip()[:200]
    children=[n for n in all_nodes if n['parent_id']==target]
    if search:
        children=[n for n in all_nodes if search.casefold() in (n['code']+' '+n['data']['title']+' '+n['data'].get('description','')).casefold()]
    for n in children:
        n['child_count']=sum(child['parent_id']==n['id'] for child in all_nodes)
    documents=[];references=[];owner=None
    if current:
        data=current['data']
        uid=s.actor(request.user) if request.user.is_authenticated else None
        documents=s.query('''SELECT d.number,v.title,l.kind_slug,l.number_slug FROM documents d
            JOIN document_versions v ON v.id=current_release(d.id)
            JOIN document_links l ON l.document_id=d.id
            WHERE d.id=ANY(%s::bigint[]) AND ((NOT d.login_required) OR can_read_version(%s,v.id)) ORDER BY d.number''',[data.get('documents',[]),uid])
        references=s.query('SELECT s.name,s.edition,r.reference,r.label FROM standard_references r JOIN standards s ON s.id=r.standard_id WHERE r.id=ANY(%s::bigint[]) ORDER BY s.name,r.reference',[data.get('references',[])])
        owners=s.query('SELECT display_name FROM users WHERE id=%s',[data['owner_id']]);owner=owners[0]['display_name'] if owners else 'Nicht zugeordnet'
    history=s.query('SELECT r.revision,r.released_at,u.display_name FROM ims_process_revisions r JOIN users u ON u.id=r.actor_id WHERE r.process_id=%s ORDER BY r.revision DESC',[target]) if current and manager else []
    return render(request,'dms/processes.html',{'history':history,**{'current':current,'crumbs':crumbs,'children':children,'search':search,'manager':manager,'documents':documents,'references':references,'owner':owner}})


@login_required
def edit(request,target=None):
    require_qmb(request.user)
    all_nodes={n['id']:n for n in processes.nodes(True)}
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
