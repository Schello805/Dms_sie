from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError
from django.shortcuts import render,redirect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST
from . import accounts,services as s
from .policies import require_settings_admin
from .account_forms import CreateAccountForm,PasswordForm,AccountStatusForm


@login_required
@sensitive_post_parameters('password1','password2')
def create(request):
    require_settings_admin(request.user)
    form = CreateAccountForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            accounts.create_account(request.user,**form.cleaned_data)
        except ValidationError as error:
            form.add_error(None,error)
        except IntegrityError:
            form.add_error('username','Dieser Benutzername ist bereits vergeben.')
        else:
            messages.success(request,'Benutzer als Leser angelegt. Weitere Rollen können jetzt zugeordnet werden.')
            return redirect('user_roles')
    return render(request,'dms/account_form.html',{'form':form,'title':'Benutzer anlegen','button':'Benutzer anlegen'})


@login_required
@require_POST
def status(request):
    require_settings_admin(request.user)
    form = AccountStatusForm(request.POST)
    if form.is_valid():
        try:
            accounts.set_active(request.user,**form.cleaned_data)
        except ValidationError as error:
            messages.error(request,' '.join(error.messages))
        else:
            messages.success(request,'Kontostatus geändert. Bestehende Anmeldungen wurden beendet.')
    else:
        messages.error(request,'Benutzer, Status und Begründung prüfen.')
    return redirect('user_roles')


@login_required
@sensitive_post_parameters('old_password','password1','password2')
def password(request,user_id=None):
    actor = s.actor(request.user)
    target = user_id or actor
    own = target==actor
    if not own:
        require_settings_admin(request.user)
    rows = s.query('SELECT display_name FROM users WHERE id=%s',[target])
    if not rows:
        raise PermissionDenied('Benutzer nicht verfügbar.')
    form = PasswordForm(request.POST or None)
    if own:
        form.fields['old_password'].required=True
    else:
        form.fields.pop('old_password')
        form.fields['reason'].initial='IT-Passwortzurücksetzung'
    if request.method=='POST' and form.is_valid():
        try:
            accounts.change_password(request.user,target,**form.cleaned_data)
        except ValidationError as error:
            form.add_error(None,error)
        else:
            if own:
                logout(request)
                messages.success(request,'Passwort geändert. Bitte erneut anmelden.')
                return redirect('login')
            messages.success(request,'Passwort zurückgesetzt. Bestehende Anmeldungen des Benutzers wurden beendet.')
            return redirect('user_roles')
    return render(request,'dms/account_form.html',{'form':form,'title':'Passwort ändern' if own else 'Passwort zurücksetzen: '+rows[0]['display_name'],'button':'Passwort speichern'})
