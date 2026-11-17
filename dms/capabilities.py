"""One UI permission projection per request; database mutation guards remain authoritative."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    uid: int | None = None
    author: bool = False
    qmb: bool = False
    admin: bool = False
    can_create: bool = False
    name: str = ''
    email: str = ''

    @property
    def roles(self):
        return (['Autor'] if self.author else [])+(['QMB'] if self.qmb else [])+(['Admin'] if self.admin else []) or ['Leser']


def for_user(user):
    if not user.is_authenticated or not user.is_active:return Capabilities()
    from .services import query
    rows=query("""SELECT u.id AS uid,u.display_name AS name,u.email,is_qmb(u.id) AS qmb,
      has_role(u.id,'ADMIN',NULL,NULL) AS admin,
      EXISTS(SELECT 1 FROM effective_role_assignments r WHERE r.user_id=u.id AND r.role='AUTHOR') AS author,
      (is_qmb(u.id) OR EXISTS(SELECT 1 FROM effective_role_assignments r WHERE r.user_id=u.id AND r.role='AUTHOR' AND r.document_id IS NULL)) AS can_create
      FROM users u JOIN auth_user a ON a.id=u.auth_user_id WHERE u.auth_user_id=%s AND u.active AND a.is_active""",[user.pk])
    return Capabilities(**rows[0]) if rows else Capabilities()


def for_request(request):
    if not hasattr(request,'_ims_capabilities'):
        from django.contrib.auth.models import AnonymousUser
        request._ims_capabilities=for_user(getattr(request,'user',AnonymousUser()))
    return request._ims_capabilities
