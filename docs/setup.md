# Setup and configuration

[Back to README](../README.md)

## Requirements

- Linux with network namespaces, veth, and `/dev/net/tun`.
- systemd, Python 3.9+, Bash, iproute2, iptables, Tailscale, sudo, util-linux (`runuser`, `mount`), and normal core utilities.
- Root access for installation, removal, and entering namespaces. Shells drop privileges to the invoking user.
- An ordinary IPv4 default uplink and IPv4 forwarding enabled.

Developed on Arch Linux with the iptables nft backend. Distribution-specific firewalls may need integration. This tool intentionally leaves the host Tailscale service and the global forwarding setting unchanged.

Check forwarding with `sysctl net.ipv4.ip_forward`. If disabled and you want to enable it persistently:

```bash
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/90-tailnet-shell.conf
sudo sysctl --system
```

That forwarding setting affects the host globally; the installer never creates this file. Remove it yourself if you created it and later no longer need forwarding. Docker may also require forwarding.

## Install an instance

Choose a short instance name. The installer automatically selects an unused private IPv4 `/30` subnet and prints the selection.

```bash
sudo ./tailnet-shell install client \
  --dns-suffix example.ts.net

client-tailscale up --hostname=mycomputer-client
client-tailscale status
client-shell
```

For the simplest setup, just run `sudo ./tailnet-shell install client`. Automatic selection checks IPv4 routes in all host routing tables, configured interface addresses, and subnets reserved by managed instances, including stopped instances. It tries `10.203.0.0/16` first, then the remaining available space in `10.0.0.0/8`, `172.16.0.0/12`, and `192.168.0.0/16`. The selected subnet is saved in the instance configuration and reused at boot. Concurrent installation and removal commands are serialized to prevent duplicate allocations.

To choose a subnet yourself, supply `--subnet 10.203.80.0/30`. Explicit subnets receive the same overlap checks. Automatic selection cannot predict networks added later or remote networks that have not yet been installed as host routes.

Authenticate using the account for the desired tailnet. This creates a separate device, subject to that tailnet's access and device approval policies. No state is copied from the host daemon.

`--dns-suffix` is optional. Use the tailnet's actual MagicDNS suffix, available in `client-tailscale status --json` under `CurrentTailnet.MagicDNSSuffix`. Without it, use full DNS names or tailnet IP addresses. To add or change the suffix later, edit `/etc/tailnet-shell/client/resolv.shell`; newly opened shells use the change immediately.

The daemon uses public bootstrap DNS (`1.1.1.1`, `9.9.9.9` by default). Override this with `--bootstrap-dns ADDRESS [ADDRESS ...]`. Pick resolvers reachable through the uplink; host loopback resolvers are unavailable inside the namespace. Shells use their own Tailscale resolver at `100.100.100.100`. A namespace-specific NSS configuration prevents glibc from falling back to the host's systemd-resolved service.

For another instance, choose a different name; its subnet is allocated separately:

```bash
sudo ./tailnet-shell install lab
lab-tailscale up
lab-shell
```

Installed scripts and services are independent of the repository's location. The installer refuses to overwrite an existing installation; it is not an upgrade command. State retained by an earlier uninstall is reused when reinstalling the same name.
