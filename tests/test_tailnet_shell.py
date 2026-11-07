import argparse
import importlib.machinery
import importlib.util
import ipaddress
import json
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
    def launcher_calls(self, arguments, control_url='', fail_set=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'calls.jsonl'
            sudo = root / 'sudo'
            sudo.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
socket = next(i for i, arg in enumerate(args) if arg.startswith('--socket='))
command = args[socket + 1:]
with Path(os.environ['CALL_LOG']).open('a') as stream:
    stream.write(json.dumps(command) + '\\n')
if command == ['debug', 'prefs']:
    print(json.dumps({'ControlURL': os.environ['CONTROL_URL']}))
if command and command[0] == 'set' and os.environ['FAIL_SET'] == '1':
    sys.exit(3)
''')
            sudo.chmod(0o755)
            script = app.rendered_files(options())['/usr/local/bin/client-tailscale'][0]
            env = dict(os.environ, PATH=f'{root}:' + os.environ['PATH'], CALL_LOG=str(log),
                       CONTROL_URL=control_url, FAIL_SET='1' if fail_set else '0')
            result = subprocess.run(['bash', '-s', '--', *arguments], input=script,
                                    text=True, env=env, capture_output=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_launcher_disables_dns_on_initial_up_login_and_set(self):
        cases = [(['up'], [['debug', 'prefs'], ['up', '--accept-dns=false']]),
                 (['up', '--hostname=my-client'], [['up', '--accept-dns=false', '--hostname=my-client']]),
                 (['login'], [['login', '--accept-dns=false']]),
                 (['set', '--accept-routes'], [['set', '--accept-dns=false', '--accept-routes']])]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                result, calls = self.launcher_calls(arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, expected)

    def test_launcher_keeps_bare_up_and_stops_if_dns_change_fails(self):
        result, calls = self.launcher_calls(['up'], control_url='https://controlplane.example')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [['debug', 'prefs'], ['set', '--accept-dns=false'], ['up']])
        result, calls = self.launcher_calls(['up'], control_url='https://controlplane.example', fail_set=True)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(calls, [['debug', 'prefs'], ['set', '--accept-dns=false']])

    def test_launcher_rejects_dns_enable_and_accepts_explicit_false(self):
        for flag in ('--accept-dns', '--accept-dns=true', '-accept-dns=1'):
            with self.subTest(flag=flag):
                result, calls = self.launcher_calls(['up', flag])
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])
        result, calls = self.launcher_calls(['up', '--accept-dns=false'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [['up', '--accept-dns=false', '--accept-dns=false']])

    def test_launcher_help_status_and_empty_set_do_not_change_preferences(self):
        for arguments in (['up', '--help'], ['login', '-h'], ['set'], ['status', '--json']):
            with self.subTest(arguments=arguments):
                result, calls = self.launcher_calls(arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [arguments])

    def test_automatic_subnet_skips_ranges_and_allocates_distinct_links(self):
        occupied = [ipaddress.ip_network('10.203.0.0/24'),
                    ipaddress.ip_network('10.203.1.0/30'),
                    ipaddress.ip_network('10.203.1.6/32')]
        first = app.choose_subnet(occupied)
        self.assertEqual(first, '10.203.1.8/30')
        occupied.append(ipaddress.ip_network(first))
        second = app.choose_subnet(occupied)
        self.assertEqual(second, '10.203.1.12/30')
        self.assertTrue(all(not ipaddress.ip_network(second).overlaps(net) for net in occupied))

    def test_automatic_subnet_falls_back_and_reports_exhaustion(self):
        occupied = [ipaddress.ip_network('10.0.0.0/8')]
        self.assertEqual(app.choose_subnet(occupied), '172.16.0.0/30')
        occupied.append(ipaddress.ip_network('172.16.0.0/12'))
        self.assertEqual(app.choose_subnet(occupied), '192.168.0.0/30')
        occupied.append(ipaddress.ip_network('192.168.0.0/16'))
        with self.assertRaisesRegex(RuntimeError, 'No unused private /30'):
            app.choose_subnet(occupied)

    def test_explicit_subnet_is_preserved_or_rejected_on_overlap(self):
        existing = [ipaddress.ip_network('10.203.80.0/24')]
        self.assertEqual(app.resolve_subnet('10.205.0.0/30', existing), '10.205.0.0/30')
        with self.assertRaisesRegex(RuntimeError, 'Subnet overlaps'):
            app.resolve_subnet('10.203.80.4/30', existing)

    def test_allocation_checks_routes_interfaces_and_inactive_instances(self):
        responses = [subprocess.CompletedProcess([], 0, json.dumps([
            {'dst': 'default'}, {'dst': '0.0.0.0/0'}, {'dst': '10.203.0.0/24'}])),
            subprocess.CompletedProcess([], 0, json.dumps([{'addr_info': [
                {'family': 'inet', 'local': '10.203.1.1', 'prefixlen': 30}]}]))]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / 'offline').mkdir()
            (config / 'offline/instance.json').write_text(json.dumps({'subnet': '10.203.1.4/30'}))
            with patch.object(app, 'CONFIG', config), patch.object(app, 'run', side_effect=responses):
                self.assertEqual(app.choose_subnet(app.existing_subnets()), '10.203.1.8/30')

    def test_install_cli_allows_omitting_subnet(self):
        with patch('sys.argv', ['tailnet-shell', 'install', 'lab']), \
                patch.object(app, 'mutation_lock'), patch.object(app, 'install') as install:
            self.assertEqual(app.main(), 0)
            args = install.call_args.args[0]
            self.assertEqual(args.name, 'lab')
            self.assertIsNone(args.subnet)

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
