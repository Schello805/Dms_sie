from .policies import is_settings_admin,is_qmb
from .branding import branding_context

def navigation(request):
    from .services import query
    can_create = False
    author = False
    if request.user.is_authenticated and request.user.is_active:
        roles = query("SELECT bool_or(r.document_id IS NULL) AS can_create,count(*)>0 AS is_author FROM effective_role_assignments r JOIN users u ON u.id=r.user_id WHERE u.auth_user_id=%s AND u.active AND r.role='AUTHOR'",[request.user.pk])[0]
        can_create = bool(roles['can_create'])
        author = roles['is_author']
    task_count = 0
    qmb = is_qmb(request.user)
    can_create = can_create or qmb
    can_tasks = author or qmb
    if can_tasks:
        from .worklist import tasks_for
        request.worklist = getattr(request,'worklist',None) or tasks_for(request.user)
        task_count = request.worklist['work_count']
    profile = None
    admin = is_settings_admin(request.user)
    if request.user.is_authenticated:
        rows = query('SELECT display_name,email FROM users WHERE auth_user_id=%s AND active',[request.user.pk])
        name = rows[0]['display_name'] if rows else request.user.get_full_name() or request.user.username
        roles = (['Autor'] if author else [])+(['QMB'] if qmb else [])+(['Admin'] if admin else [])
        roles = roles or ['Leser']
        profile = {'name':name,'email':rows[0]['email'] if rows else '',
                   'initials':''.join(word[0] for word in name.split()[:2]).upper(),
                   'roles':roles,'role_label':' · '.join(roles)}
    from .health import status
    health = status() if admin else None
    return {'system_health':health,'account_info':profile,**branding_context(),'can_tasks':can_tasks,'can_author_tasks':author or qmb,'task_count':task_count,'can_admin_settings':admin,'can_create_documents':can_create,'can_qmb_management':qmb,'can_find_management':qmb or admin}
