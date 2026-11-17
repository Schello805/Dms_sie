"""Frozen, readable document URLs; numeric routes stay compatible."""
from django.urls import reverse
from .services import query


def document_url(document_id):
    rows=query('SELECT kind_slug,number_slug FROM document_links WHERE document_id=%s',[document_id])
    if not rows:
        return reverse('read_current',args=[document_id])
    return reverse('read_named',kwargs=rows[0])
