"""Validated raster branding, immutable revisions and atomic selection."""
import hashlib
import io
from pathlib import Path
import warnings
from django.core.exceptions import ValidationError
from django.db import transaction
from PIL import Image,ImageOps,UnidentifiedImageError
from . import services as s
from .policies import require_settings_admin

MAX_UPLOAD = 5*1024*1024


def generate_assets(uploaded):
    if not uploaded:
        raise ValidationError('Bitte ein Logo als PNG, JPEG oder WebP auswählen.')
    data = uploaded.read(MAX_UPLOAD+1)
    if not data or len(data)>MAX_UPLOAD:
        raise ValidationError('Das Logo muss zwischen 1 Byte und 5 MiB groß sein.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as check:
                if check.format not in ('PNG','JPEG','WEBP') or getattr(check,'is_animated',False):
                    raise ValidationError('Nur nicht animierte PNG-, JPEG- oder WebP-Bilder sind erlaubt.')
                if min(check.size)<64 or max(check.size)>4096:
                    raise ValidationError('Das Logo muss je Seite zwischen 64 und 4096 Pixel groß sein.')
                check.verify()
            with Image.open(io.BytesIO(data)) as decoded:
                image = ImageOps.exif_transpose(decoded).convert('RGBA')
                image.thumbnail((2048,2048),Image.Resampling.LANCZOS)
                image.info.clear()
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,EOFError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValidationError('Die Datei ist kein gültiges unterstütztes Bild.')
    def png(img):
        output = io.BytesIO()
        img.save(output,format='PNG',optimize=True)
        return output.getvalue()
    logo = png(image)
    if len(logo)>8*1024*1024:
        raise ValidationError('Das aufbereitete Logo ist zu groß. Bitte ein kleineres Bild wählen.')
    size = max(image.size)
    square = Image.new('RGBA',(size,size),(255,255,255,0))
    square.alpha_composite(image,((size-image.width)//2,(size-image.height)//2))
    icons = {n:png(square.resize((n,n),Image.Resampling.LANCZOS)) for n in (32,180,192)}
    ico = io.BytesIO()
    square.resize((256,256),Image.Resampling.LANCZOS).save(ico,format='ICO',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    return {'logo':logo,'favicon':ico.getvalue(),'icons':icons,'sha256':hashlib.sha256(data).hexdigest()}


@transaction.atomic
def replace_logo(user,uploaded,reason):
    uid = require_settings_admin(user)
    if not reason.strip():
        raise ValidationError('Eine Begründung für den Logowechsel ist erforderlich.')
    assets = generate_assets(uploaded)
    before = s.query('SELECT revision_id FROM branding_settings WHERE id=1 FOR UPDATE')[0]['revision_id']
    revision = s.query('''INSERT INTO branding_revisions(actor_id,original_name,source_sha256,reason,logo_png,favicon_ico,icon_32,icon_180,icon_192)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',[uid,Path(uploaded.name).name[:255],assets['sha256'],reason,assets['logo'],assets['favicon'],assets['icons'][32],assets['icons'][180],assets['icons'][192]])[0]['id']
    s.query('UPDATE branding_settings SET revision_id=%s WHERE id=1',[revision])
    import json
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CHANGE_MAIN_LOGO','settings','branding',%s,%s::jsonb)",[uid,reason,json.dumps({'before_revision':before,'revision':revision,'source_sha256':assets['sha256']})])
    return revision


@transaction.atomic
def select_logo(user,revision_id,reason):
    uid = require_settings_admin(user)
    if not reason.strip():
        raise ValidationError('Eine Begründung ist erforderlich.')
    before = s.query('SELECT revision_id FROM branding_settings WHERE id=1 FOR UPDATE')[0]['revision_id']
    if revision_id is not None and not s.query('SELECT id FROM branding_revisions WHERE id=%s',[revision_id]):
        raise ValidationError('Diese Logo-Version ist nicht vorhanden.')
    s.query('UPDATE branding_settings SET revision_id=%s WHERE id=1',[revision_id])
    import json
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'SELECT_MAIN_LOGO','settings','branding',%s,%s::jsonb)",[uid,reason,json.dumps({'before_revision':before,'revision':revision_id})])
