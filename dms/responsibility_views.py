from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from . import services as s, responsibilities
from .audit_text import OptionalReasonField
from .form_ui import AppForm
from .policies import require_qmb


class TransferForm(AppForm):
    previous = forms.TypedChoiceField(label='Bisheriger verantwortlicher Autor', coerce=int)
    successor = forms.TypedChoiceField(label='Neuer verantwortlicher Autor', coerce=int)
    documents = forms.TypedMultipleChoiceField(label='Dokumente übertragen', coerce=int, widget=forms.CheckboxSelectMultiple)
    reason = OptionalReasonField(label='Grund der Änderung', max_length=4000, required=False)
    confirmed = forms.BooleanField(label='Ich bestätige die Übertragung der ausgewählten Dokumente einschließlich offener Aufgaben.')

    def __init__(self, *args, previous=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['previous'].choices = [(u['id'],u['display_name']) for u in s.query('SELECT u.id,u.display_name FROM users u WHERE EXISTS(SELECT 1 FROM documents d WHERE d.owner_id=u.id) ORDER BY u.display_name,u.id')]
        self.fields['successor'].choices = [('', 'Bitte auswählen')]+[(u['id'],u['display_name']) for u in s.query("SELECT u.id,u.display_name FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.active AND a.is_active AND (is_qmb(u.id) OR EXISTS(SELECT 1 FROM effective_role_assignments r WHERE r.user_id=u.id AND r.role='AUTHOR')) ORDER BY u.display_name,u.id")]
        self.fields['documents'].choices = [(d['id'],f"{d['number']} · {d['title']} · {d['department']}"+(' · deaktiviert' if not d['active'] else '')) for d in s.query('SELECT d.id,d.number,d.active,dep.name AS department,v.title FROM documents d JOIN departments dep ON dep.id=d.responsible_department_id JOIN LATERAL (SELECT title FROM document_versions WHERE document_id=d.id ORDER BY major DESC,minor DESC LIMIT 1) v ON true WHERE d.owner_id=%s ORDER BY d.number LIMIT 5000',[previous])]


@login_required
def overview(request):
    require_qmb(request.user)
    try:
        previous = int(request.POST.get('previous', '') if request.method=='POST' else request.GET.get('previous', ''))
    except (ValueError, TypeError):
        previous = None
    form = TransferForm(request.POST or None, previous=previous, initial={'previous':previous})
    if request.method=='POST' and form.is_valid():
        try:
            count = responsibilities.transfer(request.user, **{k:form.cleaned_data[k] for k in ('previous','successor','documents','reason')})
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request,f'{count} Dokumente übertragen. Historische Ersteller, Freigaben und Dokumentlinks bleiben erhalten.')
            return redirect('responsibilities')
    return render(request,'dms/responsibilities.html',{'form':form,'previous':previous})
