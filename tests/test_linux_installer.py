"""Installer unit tests run without Linux privileges, services or network."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1] / 'scripts/install_linux.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def state(self):
        return dict(hosts=['dms.example.internal', '192.168.10.20'], port=8080,
                    secret='stable-secret', passwords={role:'secret-'+role for role in installer.ROLES})

    def test_repo_ref_and_host_validation_excludes_injection_and_embedded_tokens(self):
        for value in ['https://github.com/company/dms.git', 'git@github.com:company/dms']:
            self.assertEqual(installer.validate_repo(value), value)
        for value in ['https://token@github.com/company/dms', 'file:///tmp/repo', 'https://evil.test/a/b', 'https://github.com/a/b;id']:
            with self.assertRaises(ValueError):
                installer.validate_repo(value)
        for value in ['main', 'v0.2.1', 'feature/linux', 'a'*40]:
            self.assertEqual(installer.validate_ref(value), value)
        for value in ['--upload-pack=id', '../main', 'main;id', 'a\nb']:
            with self.assertRaises(ValueError):
                installer.validate_ref(value)
        for value in ['dms.intern', '192.168.1.10', 'localhost']:
            self.assertEqual(installer.validate_host(value), value)
        for value in ['http://dms.intern', 'dms.intern; include /etc/passwd;', 'a\nb', '*.example.test', 'dms..firma.de', '-dms.firma.de', 'dms-.firma.de', 'x'*64+'.de']:
            with self.assertRaises(ValueError):
                installer.validate_host(value)
        for value in ['0','65536','bad']:
            with self.assertRaises(ValueError):
                installer.validate_port(value)

    def test_private_atomic_state_and_preserved_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'install.json'
            installer.write_private(target, json.dumps(self.state()))
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(target.read_text())['secret'], 'stable-secret')
            installer.write_private(target, '{}')
            self.assertEqual(target.read_text(), '{}')
            self.assertEqual(list(Path(directory).glob('*.tmp-*')), [])

    def test_database_env_keeps_owner_credentials_out_of_runtime(self):
        state = self.state()
        app = installer.environment(state, 'app')
        self.assertEqual(app['PGUSER'], 'ims_dms_app')
        self.assertEqual(app['DMS_INTERNAL_HTTP'], '1')
        self.assertNotIn('secret-owner', app.values())
        self.assertEqual(installer.environment(state,'notify')['DMS_SECRET_KEY'], app['DMS_SECRET_KEY'])

    def test_services_bind_gunicorn_to_loopback_and_avoid_lxc_mount_namespaces(self):
        normal = installer.service_unit('gunicorn --bind 127.0.0.1:8000', 'web', False)
        container = installer.service_unit('gunicorn --bind 127.0.0.1:8000', 'web', True)
        self.assertIn('ProtectSystem=strict', normal)
        self.assertNotIn('PrivateTmp=', container)
        self.assertIn('User=ims-dms', container)
        self.assertIn('NoNewPrivileges=true', container)
        nginx = installer.nginx_config(self.state())
        self.assertIn('listen 8080 default_server;', nginx)
        self.assertIn('proxy_pass http://127.0.0.1:8000;', nginx)
        self.assertNotIn('alias ', nginx)

    def test_owned_config_can_update_but_foreign_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'manage'
            wrapper = '#!/bin/sh\n' + installer.MARKER + '\nexit 0\n'
            installer.managed_file(file, wrapper)
            installer.managed_file(file, wrapper)
            file.write_text('unrelated config')
            with self.assertRaises(RuntimeError):
                installer.managed_file(file, wrapper)
            self.assertEqual(file.read_text(), 'unrelated config')

    def test_dry_run_never_installs_or_connects(self):
        with patch('sys.argv', ['install_linux.py','--dry-run','--repo','https://github.com/example/dms','--host','localhost']), patch.object(installer,'install') as install, patch('builtins.print'):
            installer.main()
            install.assert_not_called()

    def test_installation_does_not_require_or_configure_a_fixed_ip(self):
        args=installer.parser().parse_args(['--repo','https://github.com/example/dms'])
        self.assertIsNone(args.host)
        state=self.state();state['hosts']=[]
        self.assertEqual(installer.environment(state,'app')['DMS_DYNAMIC_HOSTS'],'1')
        self.assertIn('server_name _;',installer.nginx_config(state))
        self.assertEqual(installer.environment(state,'app')['DMS_ALLOWED_HOSTS'],'localhost,127.0.0.1')

    def test_domain_prompt_retries_and_registers_validated_names(self):
        args = installer.parser().parse_args([])
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=['https://bad.test', 'DMS.firma.de, dms.intern,DMS.firma.de']), patch('builtins.print'):
            installer.configure_hosts(args, None)
        self.assertEqual(args.host, ['dms.firma.de', 'dms.intern'])
        state = self.state() | {'hosts': args.host}
        self.assertIn('dms.firma.de', installer.environment(state, 'app')['DMS_ALLOWED_HOSTS'])
        self.assertIn('dms.firma.de', installer.nginx_config(state))

    def test_domain_prompt_allows_ip_only_and_handles_closed_input(self):
        args = installer.parser().parse_args([])
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value=''), patch('builtins.print'):
            installer.configure_hosts(args, None)
        self.assertEqual(args.host, [])
        args = installer.parser().parse_args([])
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=EOFError), patch('builtins.print'):
            with self.assertRaises(RuntimeError): installer.configure_hosts(args, None)

    def test_domain_prompt_never_silently_skips_without_terminal(self):
        with patch.object(installer.sys.stdin, 'isatty', return_value=False):
            with self.assertRaises(RuntimeError): installer.configure_hosts(installer.parser().parse_args([]), None)
        with patch('builtins.input') as prompt:
            for arguments, state in [(['--non-interactive'], None), (['--host', 'dms.firma.de'], None), (['--update'], self.state())]:
                installer.configure_hosts(installer.parser().parse_args(arguments), state)
            prompt.assert_not_called()

    def test_database_grants_are_applied_to_all_dedicated_roles(self):
        with patch.object(installer,'psql') as psql:
            installer.apply_grants(Path(__file__).resolve().parents[1])
            self.assertEqual(psql.call_count,4)
            statements = '\n'.join(call.args[0] for call in psql.call_args_list)
            for role in ('ims_dms_app','ims_dms_index','ims_dms_notify','ims_dms_backup'):
                self.assertIn(role,statements)
            self.assertNotIn('GRANT ims_dms_owner',statements)

    def test_update_migration_failure_keeps_services_stopped_and_preserves_backup(self):
        self.check_update_failure(migration=True)

    def test_update_backup_failure_never_runs_migrations_and_restarts_old_services(self):
        self.check_update_failure(migration=False)

    def check_update_failure(self, migration):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, config = root/'app', root/'etc'
            base.mkdir(); config.mkdir()
            old, new = base/'old', base/'new'
            old.mkdir(); new.mkdir(); (base/'current').symlink_to(old)
            backup = root/'backup'; backup.mkdir()
            state = self.state() | dict(complete=True,repo='https://github.com/example/dms',ref='main',admin_user='admin')
            state_file = config/'install.json';state_file.write_text(json.dumps(state))
            def manage(release, state, role, *arguments, **kwargs):
                if role=='backup':
                    if not migration: raise RuntimeError('backup failure')
                    return SimpleNamespace(stdout=str(backup)+'\n')
                if arguments[0]=='migrate': raise RuntimeError('migration failure')
                return SimpleNamespace(stdout='')
            args = installer.parser().parse_args(['--update'])
            with patch.multiple(installer,BASE=base,CONFIG=config,STATE=state_file,DATA=root/'data',BACKUPS=root/'backups'), patch.object(installer,'run') as run, patch.object(installer,'psql',return_value=SimpleNamespace(stdout='170000')), patch.object(installer,'prepare_release',return_value=new), patch.object(installer,'setup_database'), patch.object(installer,'manage',side_effect=manage) as manage_mock, patch.object(installer.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='')) as subprocess_mock, patch('builtins.print'):
                with self.assertRaises(RuntimeError):
                    installer._install_locked(args)
                if migration:
                    self.assertTrue((backup/'install.json').is_file())
                    self.assertEqual((backup/'install.json').stat().st_mode & 0o777,0o600)
                    subprocess_mock.assert_any_call(['systemctl','stop',*installer.SERVICES],check=False)
                else:
                    self.assertEqual(manage_mock.call_count,1)
                    run.assert_any_call(['systemctl','start',*installer.SERVICES,'ims-dms-backup.timer'])
                self.assertEqual((base/'current').resolve(),old.resolve())
                self.assertTrue(json.loads(state_file.read_text())['complete'])

    def test_git_and_pip_commands_use_argument_arrays_without_shell(self):
        with patch.object(installer.subprocess,'run') as run:
            installer.run(['git','fetch','origin','feature/linux'], text='not printed')
            self.assertEqual(run.call_args.args[0], ['git','fetch','origin','feature/linux'])
            self.assertNotIn('shell', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
