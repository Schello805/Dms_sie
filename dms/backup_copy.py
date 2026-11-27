"""Copy a verified backup package to a separately mounted backup destination."""
import os
from pathlib import Path
import shutil
import uuid
from .backup import verify_backup


def copy_backup(source, destination):
    source = Path(source).resolve(strict=True)
    raw_target = Path(destination).expanduser()
    if not raw_target.is_absolute() or raw_target.is_symlink():
        raise ValueError('Ein absolutes, bereits eingehängtes Sicherungsziel angeben.')
    target = raw_target.resolve(strict=True)
    if not target.is_dir() or target==source.parent or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('Ein getrenntes Sicherungsziel außerhalb des lokalen Sicherungsbaums verwenden.')
    if source.stat().st_dev==target.stat().st_dev:
        raise ValueError('Das Sicherungsziel muss auf einem getrennten eingehängten Dateisystem liegen.')
    verify_backup(source)
    final = target/source.name
    if final.exists():
        raise ValueError('Dieses Sicherungspaket existiert am Ziel bereits.')
    stage = target/('.'+source.name+'-'+uuid.uuid4().hex+'.partial')
    old_mask = os.umask(0o077)
    try:
        shutil.copytree(source,stage,symlinks=False)
        for directory, folders, files in os.walk(stage):
            Path(directory).chmod(0o700)
            for name in files:
                (Path(directory)/name).chmod(0o600)
        verify_backup(stage)
        stage.rename(final)
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True)
        raise
    finally:
        os.umask(old_mask)
    return final
