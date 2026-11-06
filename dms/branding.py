"""Public, explicitly whitelisted application brand assets."""
from django.conf import settings
from django.http import FileResponse,Http404

ASSETS = {
    'logo.png':'image/png',
    'favicon.ico':'image/vnd.microsoft.icon',
    'icon-32.png':'image/png',
    'icon-180.png':'image/png',
    'icon-192.png':'image/png',
}

def branding_context():
    from django.db import DatabaseError,transaction
    from .services import query
    from .version import APP_NAME,APP_VERSION
    revision = None
    try:
        with transaction.atomic():
            rows = query('SELECT revision_id FROM branding_settings WHERE id=1')
            revision = rows[0]['revision_id'] if rows else None
    except DatabaseError:
        pass
    return {'app_name':APP_NAME,'app_version':APP_VERSION,
        'brand_revision':f'r{revision}' if revision else 'default-'+APP_VERSION}


def asset(request,asset):
    import hashlib,io,re
    from django.db import DatabaseError,transaction
    from django.http import HttpResponseNotModified
    from .services import query
    if asset not in ASSETS:
        raise Http404
    columns = {'logo.png':'logo_png','favicon.ico':'favicon_ico','icon-32.png':'icon_32','icon-180.png':'icon_180','icon-192.png':'icon_192'}
    token = request.GET.get('v','')
    match = re.fullmatch(r'r([1-9]\d{0,17})',token)
    data = None
    degraded = False
    if not token.startswith('default-'):
        try:
            with transaction.atomic():
                if match:
                    rows = query(f'SELECT {columns[asset]} AS data FROM branding_revisions WHERE id=%s',[int(match[1])])
                else:
                    rows = query(f'SELECT r.{columns[asset]} AS data FROM branding_settings b JOIN branding_revisions r ON r.id=b.revision_id WHERE b.id=1')
                if match and not rows:
                    raise Http404
                if rows:
                    data = bytes(rows[0]['data'])
        except DatabaseError:
            degraded = True
    if data is None:
        data = (settings.BASE_DIR/'dms/static/branding'/asset).read_bytes()
    tag = '"'+hashlib.sha256(data).hexdigest()+'"'
    if request.headers.get('If-None-Match')==tag:
        response = HttpResponseNotModified()
    else:
        response = FileResponse(io.BytesIO(data),content_type=ASSETS[asset])
    response['ETag'] = tag
    response['Cache-Control'] = 'public, max-age=31536000, immutable' if match or token.startswith('default-') else 'public, max-age=0, must-revalidate'
    if degraded:
        response['Cache-Control'] = 'no-store'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    return response


def error_response(status):
    # Error rendering must also work when the database/context processors are unavailable.
    from django.http import HttpResponse
    from django.template import engines
    content = {
        400:('Ungültige Anfrage','Bitte die Adresse prüfen und die Seite erneut öffnen.'),
        403:('Kein Zugriff','Für diesen Bereich fehlen dir die erforderlichen Berechtigungen.'),
        404:('Seite nicht gefunden','Die angeforderte Seite oder Datei ist nicht verfügbar.'),
        500:('Vorübergehend nicht verfügbar','Bitte versuche es später erneut oder informiere die IT.'),
    }
    title,message = content[status]
    html = engines['django'].get_template('dms/error.html').render(dict(branding_context(),status=status,title=title,message=message))
    response = HttpResponse(html,status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def bad_request(request,exception):
    return error_response(400)


def permission_denied(request,exception):
    return error_response(403)


def page_not_found(request,exception):
    return error_response(404)


def server_error(request):
    return error_response(500)


from django.contrib.auth.decorators import login_required

@login_required
def branding_settings(request):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.shortcuts import redirect,render
    from .policies import require_settings_admin
    from .forms import BrandingForm
    from .branding_uploads import replace_logo,select_logo
    from .services import query
    require_settings_admin(request.user)
    form = BrandingForm(request.POST or None,request.FILES or None,auto_id='branding_%s')
    if request.method=='POST':
        action = request.POST.get('action','upload')
        try:
            if action=='reset':
                select_logo(request.user,None,request.POST.get('reason',''))
            elif action=='restore':
                raw = request.POST.get('revision_id','')
                if not raw.isdigit() or len(raw)>18:
                    raise ValidationError('Ungültige Logo-Version.')
                select_logo(request.user,int(raw),request.POST.get('reason',''))
            elif action=='upload' and form.is_valid():
                replace_logo(request.user,form.cleaned_data['logo'],form.cleaned_data['reason'])
            elif action!='upload':
                raise ValidationError('Unbekannte Logo-Aktion.')
            else:
                raise ValidationError('Bitte die Bilddatei prüfen.')
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Hauptlogo und Favicons aktualisiert.')
            return redirect('it_settings')
    revisions = query('SELECT r.id,r.created_at,r.reason,u.display_name FROM branding_revisions r JOIN users u ON u.id=r.actor_id ORDER BY r.id DESC LIMIT 50')
    return render(request,'dms/branding_settings.html',{'logo_form':form,'revisions':revisions})
