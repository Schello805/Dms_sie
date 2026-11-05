"""Local worker/backup health, independent of document content and secrets."""
import json
import os
from pathlib import Path
import shutil
import time
from django.conf import settings

NAMES = {'index','notifications','backup'}


def heartbeat(name, status='ok'):
    if name not in NAMES or status not in ('ok','error'):
        raise ValueError('Unknown health event')
    directory = Path(settings.HEALTH_DIR)
    temporary = directory / (name + '-' + str(os.getpid()) + '.tmp')
    try:
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary.write_text(json.dumps({'time':time.time(),'status':status}))
        temporary.chmod(0o600)
        # Root backup publishes a group-readable indicator, never credentials.
        if os.geteuid()==0:
            import grp
            os.chown(temporary,0,grp.getgrnam('ims-dms').gr_gid)
            temporary.chmod(0o640)
        temporary.replace(directory / (name+'.json'))
    except (OSError,KeyError):
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def status():
    from . import services as s
    enabled = s.query('SELECT enabled FROM notification_settings WHERE id=1')[0]['enabled']
    notices=[]
    items=[]
    now=time.time()
    for name,label,maximum,required in (
        ('index','Volltextdienst',300,True),
        ('notifications','Erinnerungsdienst',300,enabled),
        ('backup','Letzte erfolgreiche Sicherung',36*3600,True),
    ):
        age=None
        state='missing'
        try:
            data=json.loads((Path(settings.HEALTH_DIR)/(name+'.json')).read_text())
            age=max(0,int(now-float(data['time'])))
            state='ok' if data['status']=='ok' and age<=maximum else 'error'
        except (OSError,ValueError,KeyError,TypeError):
            pass
        if not required:
            state='disabled'
        if required and state!='ok':
            notices.append(label+': '+('noch kein Nachweis' if state=='missing' else 'fehlgeschlagen oder Rückmeldung überfällig'))
        items.append({'label':label,'state':state,'age_minutes':None if age is None else age//60})
    root=Path(settings.MEDIA_ROOT)
    try:
        disk=shutil.disk_usage(root if root.exists() else root.parent)
        if disk.free < max(2*1024**3,disk.total*0.1):
            notices.append('Dateispeicher wird knapp: weniger als 10 % oder 2 GiB frei.')
    except OSError:
        notices.append('Dateispeicher konnte nicht geprüft werden.')
    return {'items':items,'notices':notices,'count':len(notices)}
