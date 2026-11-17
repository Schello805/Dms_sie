from .policies import is_settings_admin,is_qmb
from .branding import branding_context

def navigation(request):
    from .capabilities import for_request
    caps=for_request(request)
    can_create,author,qmb=caps.can_create,caps.author,caps.qmb
    task_count = 0
    can_tasks = author or qmb
    if can_tasks:
        from .worklist import tasks_for
        request.worklist = getattr(request,'worklist',None) or tasks_for(request.user)
        task_count = request.worklist['work_count']
    profile = None
    admin = caps.admin
    if getattr(request,'user',None) and request.user.is_authenticated:
        name=caps.name or request.user.get_full_name() or request.user.username
        profile={'name':name,'email':caps.email,'initials':''.join(word[0] for word in name.split()[:2]).upper(),
                 'roles':caps.roles,'role_label':' · '.join(caps.roles)}
    from .health import status
    health = status() if admin else None
    return {'current_actor_id':caps.uid,'system_health':health,'account_info':profile,**branding_context(),'can_tasks':can_tasks,'can_author_tasks':author or qmb,'task_count':task_count,'can_admin_settings':admin,'can_create_documents':can_create,'can_qmb_management':qmb,'can_find_management':qmb or admin}
