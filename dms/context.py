from .policies import is_settings_admin,is_qmb
from .branding import branding_context

def navigation(request):
    from .services import query
    can_create = False
    if request.user.is_authenticated and request.user.is_active:
        can_create = bool(query("SELECT 1 FROM effective_role_assignments r JOIN users u ON u.id=r.user_id WHERE u.auth_user_id=%s AND u.active AND r.role='AUTHOR' AND r.document_id IS NULL LIMIT 1",[request.user.pk]))
    task_count = 0
    qmb = is_qmb(request.user)
    can_tasks = can_create or qmb
    if can_tasks:
        from .services import workflow_tasks
        from .simple_workflow import returned_tasks
        task_count = len(workflow_tasks(request.user))+len(returned_tasks(request.user))
    profile = None
    admin = is_settings_admin(request.user)
    if request.user.is_authenticated:
        rows = query('SELECT display_name,email FROM users WHERE auth_user_id=%s AND active',[request.user.pk])
        name = rows[0]['display_name'] if rows else request.user.get_full_name() or request.user.username
        profile = {'name':name,'email':rows[0]['email'] if rows else '',
                   'initials':''.join(word[0] for word in name.split()[:2]).upper(),
                   'roles':['Leser']+(['Autor'] if can_create else [])+(['QMB'] if qmb else [])+(['Admin'] if admin else [])}
    return {'account_info':profile,**branding_context(),'can_tasks':can_tasks,'task_count':task_count,'can_admin_settings':admin,'can_create_documents':can_create,'can_qmb_management':qmb,'can_find_management':qmb or admin}
