"""A failed remote copy must never become a completed backup package."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from dms.backup_copy import copy_backup


class BackupCopyTests(TestCase):
    def test_rejects_same_filesystem_and_cleans_failed_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'local'/'backup-1';source.mkdir(parents=True)
            (source/'database.dump').write_bytes(b'fixture')
            target=root/'remote';target.mkdir();target=target.resolve()
            with self.assertRaises(ValueError):copy_backup(source,target)
            original=Path.stat
            def different_mount(path,*args,**kwargs):
                result=original(path,*args,**kwargs)
                return SimpleNamespace(st_dev=-1) if path==target else result
            with patch.object(Path,'stat',different_mount),patch('dms.backup_copy.verify_backup',side_effect=[{},RuntimeError('corrupt copy')]):
                with self.assertRaises(RuntimeError):copy_backup(source,target)
            self.assertEqual(list(target.iterdir()),[])
            self.assertTrue((source/'database.dump').is_file())
