"""Four-level process landscape, independent drafts and immutable published revisions."""
import json
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from . import services as s
from .policies import require_qmb

LEVELS = {1:'Kernprozess',2:'Hauptprozess',3:'Einzelprozess',4:'Arbeitsprozess'}


def nodes(manage=False, target=None, search=''):
    rows=s.query('''WITH RECURSIVE tree AS (
      SELECT p.*,true AS ancestors_visible,ARRAY[p.id] AS path FROM ims_processes p WHERE parent_id IS NULL
      UNION ALL SELECT p.*,t.ancestors_visible AND t.active AND t.live IS NOT NULL,t.path||p.id
      FROM ims_processes p JOIN tree t ON p.parent_id=t.id)
      SELECT id,parent_id,level,code,revision,active,updated_at,path,
        (draft IS DISTINCT FROM live) AS has_draft,
        CASE WHEN id=%s THEN live WHEN live IS NOT NULL THEN jsonb_build_object('title',live->>'title') END AS live,
        CASE WHEN %s THEN CASE WHEN id=%s THEN draft ELSE jsonb_build_object('title',draft->>'title') END END AS draft,
        (concat(code,' ',coalesce(live,draft)->>'title',' ',coalesce(live,draft)->>'description') ILIKE %s) AS search_match
      FROM tree WHERE %s OR (active AND live IS NOT NULL AND ancestors_visible)
      ORDER BY lower(coalesce(live->>'title',draft->>'title')),id''',[target,manage,target,'%'+search+'%',manage])
    for row in rows:
        for key in ('draft','live'):
            if isinstance(row[key],str):row[key]=json.loads(row[key])
        row['data']=row['live'] or row['draft']
        row['label']=LEVELS[row['level']]
        row['child_label']=LEVELS.get(row['level']+1,'')
    return rows


@transaction.atomic
def save(user,target,parent,code,data,publish,active,reason):
    actor=require_qmb(user)
    try:
        with transaction.atomic():
            return s.query('SELECT save_ims_process(%s,%s,%s,%s,%s::jsonb,%s,%s,%s) AS id',
                [actor,target,parent,code,json.dumps(data),publish,active,reason])[0]['id']
    except IntegrityError as error:
        raise ValidationError('Diese Prozesskennung ist bereits vergeben oder eine Zuordnung ist ungültig.') from error
    except DatabaseError as error:
        if getattr(error.__cause__,'sqlstate',None) in ('P0001','P0002'):
            raise ValidationError('Angaben prüfen: aktiver Verantwortlicher, richtige Hierarchie und Beschreibung. Vor einer Veröffentlichung müssen alle übergeordneten Prozesse veröffentlicht und aktiv sein.') from error
        raise
