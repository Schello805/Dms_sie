"""Serve only the bundled UI assets, including on the local Gunicorn instance.

This explicit allowlist never exposes document storage or arbitrary static paths.
"""
from pathlib import Path
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe

ASSET_ROOT = Path(__file__).resolve().parent / 'static' / 'dms'
ASSET_TYPES = {
    'app.css': 'text/css',
    'branding.css': 'text/css',
    'app.js': 'text/javascript',
    'catalog.js': 'text/javascript',
    'catalog-state.js': 'text/javascript',
}


@require_safe
def asset(request, asset):
    content_type = ASSET_TYPES.get(asset)
    if content_type is None:
        raise Http404
    return FileResponse((ASSET_ROOT / asset).open('rb'), content_type=content_type)
