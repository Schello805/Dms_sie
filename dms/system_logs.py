"""Bounded, multiprocess-safe technical log without messages, secrets or request bodies."""
from datetime import datetime,timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import uuid
from django.conf import settings

STARTED_AT = datetime.now(timezone.utc)
MAX_BYTES = 1024*1024
BACKUPS = 3
_thread_lock = threading.RLock()


def _name(value,limit=120):
    return re.sub(r'[^A-Za-z0-9_.<>/-]','_',str(value))[:limit]


def _event(record):
    event = {'at':datetime.fromtimestamp(record.created,timezone.utc).isoformat(),
        'level':record.levelname,'source':_name(record.name),'event_code':'APPLICATION_ERROR',
        'exception_type':'','route':'','method':'','request_id':'','user_id':None,'frames':[]}
    if record.name.startswith('django.security'):
        event['event_code'] = 'SECURITY_REJECTION'
    if getattr(record,'event_code',None)=='LOG_SELF_TEST':
        event['event_code'] = 'LOG_SELF_TEST'
    if record.exc_info and record.exc_info[0]:
        event['exception_type'] = _name(record.exc_info[0].__name__)
        tb = record.exc_info[2]
        frames = []
        while tb:
            frames.append({'file':_name(Path(tb.tb_frame.f_code.co_filename).name),
                'function':_name(tb.tb_frame.f_code.co_name),'line':tb.tb_lineno})
            tb = tb.tb_next
        event['frames'] = frames[-16:]
    request = getattr(record,'request',None)
    if request is not None:
        event['request_id'] = str(getattr(request,'diagnostic_id',''))[:36]
        match = getattr(request,'resolver_match',None)
        event['route'] = str(getattr(match,'route','') or '')[:200]
        method = getattr(request,'method','')
        event['method'] = method if method in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS') else ''
        try:
            user_id = getattr(getattr(request,'user',None),'pk',None)
            event['user_id'] = user_id if isinstance(user_id,int) else None
        except Exception:
            pass
    # Deliberately never call getMessage(), format exception text, or inspect form/headers/locals.
    return event


def _directory():
    root = Path(settings.ERROR_LOG_DIR)
    if root.is_symlink():
        raise OSError('Unsafe log directory')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    root.chmod(0o700)
    return root


def write_event(event):
    encoded = (json.dumps(event,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
    with _thread_lock:
        root = _directory()
        lock = os.open(root/'errors.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX)
            current = root/'errors.jsonl'
            if current.exists() and current.stat().st_size+len(encoded)>MAX_BYTES:
                (root/f'errors.{BACKUPS}.jsonl').unlink(missing_ok=True)
                for index in range(BACKUPS-1,0,-1):
                    previous = root/f'errors.{index}.jsonl'
                    if previous.exists():
                        os.replace(previous,root/f'errors.{index+1}.jsonl')
                os.replace(current,root/'errors.1.jsonl')
            fd = os.open(current,os.O_CREAT|os.O_APPEND|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
            try:
                os.fchmod(fd,0o600)
                with os.fdopen(fd,'ab',closefd=False) as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            os.close(lock)


class SystemErrorHandler(logging.Handler):
    def emit(self,record):
        try:
            write_event(_event(record))
        except Exception:
            # No exception text here either: it can include sensitive paths or configuration.
            try:
                sys.stderr.write('DMS: technisches Fehlerprotokoll konnte nicht geschrieben werden.\n')
            except Exception:
                pass


def read_events(level='',limit=200):
    root = Path(settings.ERROR_LOG_DIR)
    if not root.exists():
        return [],''
    if root.is_symlink():
        return [],'Fehlerprotokoll-Verzeichnis ist nicht verwendbar.'
    rows = []
    try:
        for name in ['errors.jsonl',*[f'errors.{n}.jsonl' for n in range(1,BACKUPS+1)]]:
            path = root/name
            if not path.exists() or path.is_symlink():
                continue
            with path.open('rb') as stream:
                raw = stream.read(MAX_BYTES+16384)
            for line in raw.decode('utf-8',errors='replace').splitlines():
                try:
                    item = json.loads(line)
                    if not isinstance(item,dict):
                        continue
                    if item.get('level') not in ('WARNING','ERROR','CRITICAL'):
                        continue
                    if level and item['level']!=level:
                        continue
                    item['timestamp'] = datetime.fromisoformat(item['at'])
                    rows.append(item)
                except (ValueError,KeyError,TypeError):
                    continue
        rows.sort(key=lambda item:item['at'],reverse=True)
        return rows[:limit],''
    except OSError:
        return [],'Fehlerprotokoll kann nicht gelesen werden. Dateirechte prüfen.'


class RequestIdMiddleware:
    def __init__(self,get_response):
        self.get_response = get_response
    def __call__(self,request):
        request.diagnostic_id = str(uuid.uuid4())
        response = self.get_response(request)
        response['X-Request-ID'] = request.diagnostic_id
        return response
