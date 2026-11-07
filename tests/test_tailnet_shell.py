import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('tailnet_shell', str(ROOT / 'tailnet-shell'))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


def options(name='client', subnet='10.203.80.0/30'):
    return argparse.Namespace(name=name, subnet=subnet, dns_suffix='example.ts.net', bootstrap_dns=['1.1.1.1'])


class TailnetShellTests(unittest.TestCase):
    def test_arguments_cannot_escape_paths_or_inject_shell(self):
        for name in ('../bad', 'x;id', 'Bad', 'a' * 13, '', '-bad', 'a\nwhoami'):
            with self.subTest(name=name), self.assertRaises(argparse.ArgumentTypeError):
                app.name_type(name)
        for subnet in ('0.0.0.0/0', '100.64.0.0/30', '10.1.1.1/30', '10.1.0.0/24', '::/30'):
            with self.subTest(subnet=subnet), self.assertRaises(argparse.ArgumentTypeError):
                app.subnet_type(subnet)
        with self.assertRaises(argparse.ArgumentTypeError):
            app.suffix_type('example\nnameserver 8.8.8.8')

    def test_instances_have_distinct_resources_and_valid_scripts(self):
        first = app.rendered_files(options())
        second = app.rendered_files(options('lab', '10.203.80.4/30'))
        self.assertFalse(set(first) & set(second))
        for files in (first, second):
            for path, (content, mode) in files.items():
                self.assertNotRegex(content, r'@[A-Z]+@')
                if content.startswith('#!/usr/bin/env bash'):
                    subprocess.run(['bash', '-n'], input=content, text=True, check=True)
        network = first['/etc/tailnet-shell/client/network.sh'][0]
        self.assertIn('10.203.80.1/30', network)
        self.assertIn('10.203.80.2/30', network)
        self.assertIn('-d 100.64.0.0/10 -j REJECT', network)

    def test_cleanup_is_idempotent_after_partial_start(self):
        # Exercise Bash control flow with every network command mocked.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tool, content in {
                'ip': '#!/bin/bash\nif [[ "$*" == "netns list" ]]; then exit 0; fi\nexit 1\n',
                'iptables': '#!/bin/bash\nexit 1\n',
            }.items():
                path = root / tool
                path.write_text(content)
                path.chmod(0o755)
            runtime = root / 'runtime'
            runtime.mkdir()
            (runtime / 'uplink').write_text('wlan0\n')
            script = app.rendered_files(options())['/etc/tailnet-shell/client/network.sh'][0]
            script = script.replace('runtime=/run/tailnet-shell-client', f'runtime={runtime}')
            env = dict(os.environ, PATH=f'{root}:' + os.environ['PATH'])
            for _ in range(2):
                subprocess.run(['bash', '-s', '--', 'stop'], input=script, text=True, env=env, check=True)
            self.assertFalse((runtime / 'uplink').exists())

    def test_uninstall_refuses_open_shells(self):
        responses = [subprocess.CompletedProcess([], 0, 'tn-client\n'),
                     subprocess.CompletedProcess([], 0, '12345\n')]
        with patch.object(app, 'run', side_effect=responses), patch.object(Path, 'read_text', return_value='zsh\n'):
            with self.assertRaisesRegex(RuntimeError, 'Exit all shells'):
                app.ensure_no_shells('tn-client')

    def test_legacy_layout_uses_the_supplied_instance_name(self):
        for name in ('client', 'lab'):
            with self.subTest(name=name):
                paths = app.legacy_paths(name)
                helper, network_unit, daemon_unit, shell, cli = paths
                contents = {
                    helper: f'ip netns del ts-{name}',
                    network_unit: f'ExecStart={helper} start',
                    daemon_unit: f'--state=/var/lib/tailscale-{name}/tailscaled.state',
                    shell: f'ip netns exec ts-{name} bash',
                    cli: f'--socket=/run/tailscale-{name}/tailscaled.sock',
                }
                metadata = SimpleNamespace(st_mode=0o100755, st_uid=0)
                with patch.object(Path, 'lstat', return_value=metadata), \
                        patch.object(Path, 'read_text', autospec=True, side_effect=lambda path: contents[path]):
                    self.assertEqual(app.validate_legacy_files(name), paths)
                with patch.object(Path, 'lstat', return_value=metadata), \
                        patch.object(Path, 'read_text', return_value='unrelated file'):
                    with self.assertRaisesRegex(RuntimeError, 'expected legacy layout'):
                        app.validate_legacy_files(name)

    def test_legacy_removal_refuses_untrusted_helpers_before_mutations(self):
        metadata = SimpleNamespace(st_mode=0o100777, st_uid=1000)
        with patch.object(app, 'require_root'), patch.object(Path, 'lstat', return_value=metadata), \
                patch.object(app, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'root-owned'):
                app.uninstall_legacy(argparse.Namespace(name='client', purge_state=False))
            run.assert_not_called()

    def test_authentication_state_is_deleted_only_when_requested(self):
        state = Path('/var/lib/tailnet-shell/client')
        for purge in (False, True):
            with self.subTest(purge=purge), patch.object(app, 'run'), \
                    patch.object(app.shutil, 'rmtree') as remove, patch('builtins.print'):
                app.finish_removal(argparse.Namespace(purge_state=purge), state)
                if purge:
                    remove.assert_called_once_with(state, ignore_errors=True)
                else:
                    remove.assert_not_called()


if __name__ == '__main__':
    unittest.main()
