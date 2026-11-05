from django.utils.cache import patch_cache_control

class PrivateContentMiddleware:
    """Keep documents and search snippets out of reusable browser/proxy caches."""
    def __init__(self,get_response):
        self.get_response = get_response
    def __call__(self,request):
        response = self.get_response(request)
        if request.path.startswith(('/assets/pdfjs/6.5.438/','/assets/branding/')) or request.path=='/favicon.ico':
            return response
        patch_cache_control(response,private=True,no_store=True,no_cache=True,must_revalidate=True,max_age=0)
        return response


from django.utils.deprecation import MiddlewareMixin

class ReaderSurfaceMiddleware(MiddlewareMixin):
    """Basic employees have one table and protected document viewing/download routes."""
    def process_view(self,request,view_func,view_args,view_kwargs):
        if request.path.startswith('/assets/') or request.path=='/favicon.ico' or not request.user.is_authenticated:
            return None
        from .services import query
        rows = query("SELECT u.id FROM users u WHERE u.auth_user_id=%s AND u.active AND (is_qmb(u.id) OR has_role(u.id,'ADMIN',NULL,NULL) OR EXISTS(SELECT 1 FROM effective_role_assignments r WHERE r.user_id=u.id AND r.role='AUTHOR'))",[request.user.pk])
        request.reader_only = not bool(rows)
        if not request.reader_only:
            return None
        match = request.resolver_match
        if match and match.view_name in {'home','index','detail','read_current','pdf_viewer','preview_pdf','download','document_qr','login','logout'}:
            return None
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect
        if request.path.startswith(('/settings/','/management/')):
            raise PermissionDenied('Dieser Bereich ist für Leser nicht freigegeben.')
        if request.method in ('GET','HEAD') and match and match.view_name=='lifecycle':
            return None  # The POST-only endpoint returns 405 without disclosing document data.
        if request.method in ('GET','HEAD') and match and match.view_name in {'tasks','records','record_detail','new_record'}:
            return redirect('index')
        raise PermissionDenied('Leser können freigegebene Dokumente ansehen und herunterladen.')
