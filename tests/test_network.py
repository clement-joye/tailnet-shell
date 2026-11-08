"""Exercise the rendered networking helper with fake routing and netfilter tools."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


MOCK_TOOL = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['MOCK_ROOT'])
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'calls').open('a') as stream:
    stream.write(json.dumps([tool, *args]) + '\\n')
if tool == 'ip':
    route = (root / 'route').read_text().strip()
    if not route:
        sys.exit(2)
    print(f'1.1.1.1 from 10.203.80.2 dev {route} table 245447468')
elif tool == 'conntrack':
    if '-L' in args:
        print((root / 'flows').read_text(), end='')
    elif '-D' in args:
        (root / 'flows').write_text('')
elif tool == 'iptables':
    state = json.loads((root / 'rules').read_text())
    table = args[args.index('-t') + 1] if '-t' in args else 'filter'
    operation = next(arg for arg in args if arg in ('-R', '-F', '-A'))
    index = args.index(operation)
    key = table + ':' + args[index + 1]
    if os.environ.get('FAIL_NAT') == '1' and table == 'nat' and operation == '-A':
        sys.exit(2)
    if operation == '-R':
        state[key][int(args[index + 2]) - 1] = args[index + 3:]
    elif operation == '-F':
        state[key] = []
    else:
        state[key].append(args[index + 2:])
    (root / 'rules').write_text(json.dumps(state))
'''


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        token = hashlib.sha256(b'client').hexdigest()[:8]
        self.host = f'tn{token}h'
        self.chain = f'TN_{token}'
        self.nat = f'{self.chain}_NAT'
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        (self.runtime / 'uplink').write_text('wlan0\n')
        (self.root / 'route').write_text('proton0')
        (self.root / 'flows').write_text('udp src=10.203.80.2 stale-nat\n')
        (self.root / 'rules').write_text(json.dumps({
            f'filter:{self.chain}': [
                ['-i', self.host, '-d', '100.64.0.0/10', '-j', 'REJECT'],
                ['-i', self.host, '-o', 'wlan0', '-j', 'ACCEPT'],
                ['-i', self.host, '-j', 'REJECT']],
            f'nat:{self.nat}': [['-o', 'wlan0', '-j', 'MASQUERADE']],
        }))
        for tool in ('ip', 'iptables', 'conntrack'):
            path = self.root / tool
            path.write_text(MOCK_TOOL)
            path.chmod(0o755)
        self.script = (Path(__file__).resolve().parents[1] / 'templates/network.sh').read_text()
        for key, value in {'NAME': 'client', 'TOKEN': token, 'ADDRESS': '10.203.80.2',
                           'GATEWAY': '10.203.80.1'}.items():
            self.script = self.script.replace(f'@{key}@', value)
        self.script = self.script.replace('runtime=/run/tailnet-shell-client', f'runtime={self.runtime}')

    def refresh(self, **extra):
        env = dict(os.environ, PATH=f'{self.root}:' + os.environ['PATH'], MOCK_ROOT=str(self.root), **extra)
        return subprocess.run(['bash', '-s', '--', 'refresh'], input=self.script, text=True,
                              capture_output=True, env=env)

    def rules(self):
        return json.loads((self.root / 'rules').read_text())

    def calls(self):
        return [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]

    def test_policy_routed_vpn_replaces_forwarding_nat_and_stale_connections(self):
        result = self.refresh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0], ['ip', '-4', 'route', 'get', '1.1.1.1',
                                         'from', '10.203.80.2', 'iif', self.host])
        rules = self.rules()
        self.assertEqual(rules[f'filter:{self.chain}'][1], ['-i', self.host, '-o', 'proton0', '-j', 'ACCEPT'])
        self.assertEqual(rules[f'nat:{self.nat}'], [['-o', 'proton0', '-j', 'MASQUERADE']])
        self.assertEqual(rules[f'filter:{self.chain}'][0][-2:], ['-j', 'REJECT'])
        self.assertIn(['conntrack', '-D', '-f', 'ipv4', '-s', '10.203.80.2'], self.calls())
        self.assertEqual((self.runtime / 'uplink').read_text().strip(), 'proton0')
        # The first firewall change blocks forwarding until NAT has been rebuilt.
        changes = [call for call in self.calls() if call[0] == 'iptables']
        self.assertEqual(changes[0][-2:], ['-j', 'REJECT'])
        self.assertEqual(changes[-1][-2:], ['-j', 'ACCEPT'])

    def test_unchanged_route_does_not_touch_connections_or_firewall(self):
        (self.root / 'route').write_text('wlan0')
        self.assertEqual(self.refresh().returncode, 0)
        self.assertEqual(len(self.calls()), 1)

    def test_no_route_or_host_tailnet_route_blocks_forwarding(self):
        for route in ('', 'tailscale0', 'lo', self.host):
            with self.subTest(route=route):
                (self.runtime / 'uplink').write_text('wlan0\n')
                (self.root / 'route').write_text(route)
                result = self.refresh()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.rules()[f'filter:{self.chain}'][1][-2:], ['-j', 'REJECT'])
                self.assertEqual(self.rules()[f'nat:{self.nat}'], [])

    def test_disconnect_and_reconnect_refresh_without_recreating_namespace(self):
        for route in ('proton0', 'wlan0', '', 'proton0'):
            (self.root / 'route').write_text(route)
            self.assertEqual(self.refresh().returncode, 0)
            self.assertEqual((self.runtime / 'uplink').read_text().strip(), route)
        self.assertFalse(any('netns' in call or 'link' in call for call in self.calls()))

    def test_nat_failure_keeps_forwarding_blocked_and_can_retry(self):
        result = self.refresh(FAIL_NAT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.rules()[f'filter:{self.chain}'][1][-2:], ['-j', 'REJECT'])
        self.assertEqual((self.runtime / 'uplink').read_text().strip(), 'wlan0')
        self.assertEqual(self.refresh().returncode, 0)
        self.assertEqual((self.runtime / 'uplink').read_text().strip(), 'proton0')


if __name__ == '__main__':
    unittest.main()
