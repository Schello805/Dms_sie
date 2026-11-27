"""CI-only: allow 12 MiB of additional address space while serving original files."""
import os
from pathlib import Path
import resource

if os.environ.get('CI')!='true':
    raise RuntimeError('This constrained Gunicorn configuration is only for CI.')


def pre_request(worker, request):
    worker.download_limit = None
    if '/files/' not in request.path or '/preview/' in request.path or '/viewer/' in request.path:
        return
    fields = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    current = int(fields['VmSize'].split()[0])*1024
    previous = resource.getrlimit(resource.RLIMIT_AS)
    limit = current+12*1024*1024
    if previous[1]!=resource.RLIM_INFINITY:limit = min(limit,previous[1])
    worker.download_limit = previous
    resource.setrlimit(resource.RLIMIT_AS,(limit,previous[1]))


def post_request(worker, request, environ, response):
    if getattr(worker,'download_limit',None):
        resource.setrlimit(resource.RLIMIT_AS,worker.download_limit)
        worker.download_limit = None
