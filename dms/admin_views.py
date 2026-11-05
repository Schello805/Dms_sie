import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect,render
from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_post_parameters
from .policies import require_settings_admin
from . import directory,services as s
from .admin_forms import DirectorySettingsForm
from .system_info import snapshot
from .system_logs import read_events

@login_required
def system_diagnostics(request):
    uid = require_settings_admin(request.user)
    if request.method=='POST':
        if request.POST.get('action')=='test_log':
            logging.getLogger('dms.system').warning('Technical logging self-test',extra={'event_code':'LOG_SELF_TEST','request':request})
            s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason) VALUES (%s,'TEST_SYSTEM_LOG','settings','diagnostics','Technische Protokollierung manuell geprüft')",[uid])
            messages.success(request,'Protokolltest geschrieben. Der markierte Testeintrag ist kein Anwendungsfehler.')
        return redirect('system_diagnostics')
    level = request.GET.get('level','')
    level = level if level in ('WARNING','ERROR','CRITICAL') else ''
    events,warning = read_events(level)
    return render(request,'dms/system_diagnostics.html',{'info':snapshot(),'events':events,'log_warning':warning,'level':level})

@login_required
@sensitive_post_parameters('password')
def directory_settings(request):
    require_settings_admin(request.user)
    config = directory.load_config()
    initial = directory.public_config(config)
    form = DirectorySettingsForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:
            directory.save_config(request.user,form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'AD-/LDAP-Konfiguration gespeichert. Die Anmeldung bleibt lokal; es wurde kein Verzeichnis kontaktiert.')
            return redirect('directory_settings')
    return render(request,'dms/directory_settings.html',{'form':form,'password_set':initial['password_set'],'updated_at':initial['updated_at']})

@login_required
def user_roles(request):
    from .forms import UserRolesForm
    from .role_management import save_roles
    require_settings_admin(request.user)
    if request.method=='POST':
        form = UserRolesForm(request.POST)
        if form.is_valid():
            try:
                save_roles(request.user,**form.cleaned_data)
            except ValidationError as exc:
                messages.error(request,' '.join(exc.messages))
            else:
                messages.success(request,'Benutzerrechte aktualisiert. Alle anderen Konten bleiben Leser.')
        else:
            messages.error(request,'Benutzer und Begründung prüfen.')
        return redirect('user_roles')
    users = s.query("SELECT u.id,u.display_name,a.username,u.settings_admin,is_qmb(u.id) AS is_qmb,EXISTS(SELECT 1 FROM effective_role_assignments r WHERE r.user_id=u.id AND r.role='AUTHOR') AS is_author FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.active AND a.is_active ORDER BY u.display_name")
    return render(request,'dms/user_roles.html',{'people':users})
