from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect,render
from . import masterdata as m,services as s
from .master_forms import MasterForm,GroupGrantForm,ProfileForm
from .policies import is_qmb,is_settings_admin,require_settings_admin

BASES={
 'categories':"SELECT c.id,coalesce(c.display_name,c.name) AS title,c.active,c.review_interval_months::text||' Monate · '||l.name AS summary FROM document_categories c JOIN storage_locations l ON l.id=c.storage_location_id",
 'departments':"SELECT d.id,d.name AS title,d.active,d.code AS summary FROM departments d",
 'locations':"SELECT id,name AS title,active,description AS summary FROM storage_locations",
 'standards':"SELECT id,name AS title,active,edition AS summary FROM standards",
 'references':"SELECT r.id,r.reference||' · '||r.label AS title,r.active,s.name||' · '||s.edition||CASE WHEN s.active THEN '' ELSE ' (Norm deaktiviert)' END AS summary FROM standard_references r JOIN standards s ON s.id=r.standard_id",
 'groups':"SELECT g.id,g.name AS title,g.active,(SELECT count(*)::text FROM group_memberships WHERE group_id=g.id)||' Mitglieder' AS summary FROM dms_groups g",
}



def nav(user):
    result=[]
    for kind,(title,_) in m.KINDS.items():
        if (kind=='groups' and is_settings_admin(user)) or (kind!='groups' and is_qmb(user)):
            result.append({'kind':kind,'title':title})
    return result


@login_required
def listing(request,kind):
    if kind not in m.KINDS:raise Http404
    m.require(request.user,kind)
    search=request.GET.get('q','').strip()[:200]
    active=request.GET.get('active','1');active=active if active in ('','0','1') else '1'
    where="(%s='' OR title ILIKE %s OR summary ILIKE %s) AND (%s='' OR active=(%s='1'))"
    args=[search,'%'+search+'%','%'+search+'%',active,active]
    total=s.query('SELECT count(*) AS n FROM ('+BASES[kind]+') base WHERE '+where,args)[0]['n']
    page=Paginator(range(total),25).get_page(request.GET.get('page'))
    rows=s.query('SELECT * FROM ('+BASES[kind]+') base WHERE '+where+' ORDER BY lower(title),id LIMIT 25 OFFSET %s',args+[max(page.start_index()-1,0)])
    params=request.GET.copy();params.pop('page',None)
    return render(request,'dms/master_list.html',{'title':m.KINDS[kind][0],'kind':kind,'rows':rows,'page':page,'page_query':params.urlencode(),'search':search,'active':active,'master_nav':nav(request.user)})


@login_required
def edit(request,kind,target=None):
    if kind not in m.KINDS:raise Http404
    m.require(request.user,kind)
    try:record=m.get(kind,target) if target else {}
    except ValidationError:raise Http404
    initial=dict(record)
    if request.method=='GET' and request.GET.get('action')=='deactivate':initial['active']=False
    if request.method=='GET' and request.GET.get('action')=='activate':initial['active']=True
    grant_form=GroupGrantForm(prefix='grant') if kind=='groups' and target else None
    form=MasterForm(request.POST or None,kind=kind,record=record,initial=initial)
    if request.method=='POST':
        action=request.POST.get('operation','save')
        try:
            if kind=='groups' and target and action=='grant':
                form=MasterForm(kind=kind,record=record,initial=record)
                grant_form=GroupGrantForm(request.POST,prefix='grant')
                if grant_form.is_valid():
                    m.grant(request.user,target,**grant_form.cleaned_data)
                    messages.success(request,'Gruppenberechtigung gespeichert.')
                    return redirect('master_edit',kind=kind,target=target)
            elif kind=='groups' and target and action=='revoke':
                try:assignment=int(request.POST.get('assignment_id',''))
                except ValueError:raise ValidationError('Berechtigung auswählen.')
                m.revoke(request.user,target,assignment,request.POST.get('reason',''))
                messages.success(request,'Gruppenberechtigung entfernt.')
                return redirect('master_edit',kind=kind,target=target)
            elif action=='save' and form.is_valid():
                saved=m.save(request.user,kind,target,form.cleaned_data)
                messages.success(request,'Stammdaten gespeichert und protokolliert.')
                return redirect('master_edit',kind=kind,target=saved) if kind=='groups' else redirect('master_list',kind=kind)
        except ValidationError as error:
            if action=='grant' and grant_form is not None:grant_form.add_error(None,error)
            elif action=='revoke':
                messages.error(request,' '.join(error.messages));return redirect('master_edit',kind=kind,target=target)
            else:form.add_error(None,error)
        except DatabaseError:
            text='Änderung konnte nicht gespeichert werden. Status und Zuordnungen bitte erneut prüfen.'
            if action=='grant' and grant_form is not None:grant_form.add_error(None,text)
            elif action=='revoke':
                messages.error(request,text);return redirect('master_edit',kind=kind,target=target)
            else:form.add_error(None,text)
    grants=[]
    if kind=='groups' and target:
        grants=s.query('''SELECT r.id,r.role,coalesce(d.name,'') AS department,coalesce(doc.number,'') AS document,
          r.role IN ('READER','AUTHOR') AS editable FROM role_assignments r
          LEFT JOIN departments d ON d.id=r.department_id LEFT JOIN documents doc ON doc.id=r.document_id
          WHERE r.group_id=%s ORDER BY r.role,r.id''',[target])
    return render(request,'dms/master_edit.html',{'title':m.KINDS[kind][0],'kind':kind,'record':record,'form':form,'grant_form':grant_form,'grants':grants,'master_nav':nav(request.user)})


@login_required
def profile(request,user_id):
    actor=require_settings_admin(request.user)
    rows=s.query('SELECT u.display_name,u.email,a.username FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.id=%s',[user_id])
    if not rows:raise Http404
    form=ProfileForm(request.POST or None,initial=rows[0])
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        s.query('SELECT update_ims_profile(%s,%s,%s,%s,%s)',[actor,user_id,data['display_name'],data['email'],data['reason']])
        messages.success(request,'Benutzerprofil gespeichert. Anmeldekennung und Rollen bleiben erhalten.')
        return redirect('user_roles')
    return render(request,'dms/account_form.html',{'title':'Profil bearbeiten: '+rows[0]['username'],'form':form,'button':'Profil speichern'})
