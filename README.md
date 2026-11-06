# tailnet-shell

Run shells on different Tailscale tailnets using Linux network namespaces. A normal terminal uses the host's tailnet; a named shell uses a separate Tailscale daemon and device identity. Works with Ghostty and other terminals, without application proxy settings.

Each instance gets its own network namespace, virtual Ethernet link, IPv4 NAT rules, state directory, Unix control socket, systemd services, DNS configuration, and two launchers. Multiple named instances can run simultaneously.

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

Choose a short name and an unused private IPv4 `/30` subnet. The installer rejects overlapping routes and subnets reserved by other managed instances.

```bash
sudo ./tailnet-shell install client \
  --subnet 10.203.80.0/30 \
  --dns-suffix example.ts.net

client-tailscale up --accept-dns=false --hostname=mycomputer-client
client-tailscale status
client-shell
```

Authenticate using the account for the desired tailnet. This creates a separate device, subject to that tailnet's access and device approval policies. No state is copied from the host daemon.

`--dns-suffix` is optional. Use the tailnet's actual MagicDNS suffix, available in `client-tailscale status --json` under `CurrentTailnet.MagicDNSSuffix`. Without it, use full DNS names or tailnet IP addresses. To add or change the suffix later, edit `/etc/tailnet-shell/client/resolv.shell`; newly opened shells use the change immediately.

The daemon uses public bootstrap DNS (`1.1.1.1`, `9.9.9.9` by default). Override this with `--bootstrap-dns ADDRESS [ADDRESS ...]`. Pick resolvers reachable through the uplink; host loopback resolvers are unavailable inside the namespace. Shells use their own Tailscale resolver at `100.100.100.100`. A namespace-specific NSS configuration prevents glibc from falling back to the host's systemd-resolved service.

For another instance, choose a different name and subnet:

```bash
sudo ./tailnet-shell install lab --subnet 10.203.80.4/30
lab-tailscale up --accept-dns=false
lab-shell
```

Installed scripts and services are independent of the repository's location. The installer refuses to overwrite an existing installation; it is not an upgrade command. State retained by an earlier uninstall is reused when reinstalling the same name.

## Daily use

Run `client-shell` in a Ghostty tab to enter that tailnet. Run `exit` to return to the surrounding shell. Child processes inherit the namespace; new tabs must enter it explicitly. The shell exports `TAILNET_NAMESPACE=client` for optional prompt customization and clears standard HTTP/SOCKS proxy variables.

Use `client-tailscale` to inspect or configure the isolated daemon. Plain `tailscale` still targets the host daemon, even inside the isolated shell, because its Unix socket remains visible.

The daemon starts at boot. If the default uplink changes, close all instance shells and restart its namespace service to refresh NAT and routing:

```bash
sudo systemctl restart tailnet-shell-client-netns.service
```

For tmux, enter the namespace explicitly in every pane, for example:

```tmux
bind-key C new-window -n client 'client-shell'
```

Alternatively start a dedicated tmux server inside the namespace using a distinct socket (`tmux -L client new-session`). Attaching to an existing host tmux server does not move its panes into the namespace.

## Uninstall a named instance

Exit all its shells and stop its applications first. Removal refuses to proceed if processes other than the daemon remain in the namespace.

```bash
sudo ./tailnet-shell uninstall client
```

This stops and removes its services, launchers, namespace, virtual link, scoped firewall rules, and DNS configuration. Authentication state remains in `/var/lib/tailnet-shell/client` for later reuse. To delete that state too, choose this option **when uninstalling**:

```bash
sudo ./tailnet-shell uninstall client --purge-state
```

Neither command deletes the device registration from the tailnet admin console. Local state deletion requires fresh authentication on reinstall. To delete retained state after an uninstall, remove the specific instance directory under `/var/lib/tailnet-shell` yourself.

## Remove the original `/tmp/install-work-tailnet.sh` installation

The original installer is archived under `legacy/` for reproducibility. Your existing installation can continue to run; creating this repository does not migrate it.

Exit all `work-shell` sessions and stop their applications, then run:

```bash
sudo ./tailnet-shell uninstall-legacy-work
```

This removes `tailscaled-work.service`, `work-tailnet-netns.service`, the `ts-work` namespace, its firewall rules and virtual link, `/usr/local/bin/work-shell`, `/usr/local/bin/work-tailscale`, and their configuration/helper files. It checks the five installed scripts and units against the archived original before stopping anything. Modified or missing files require manual review.

State is preserved in `/var/lib/tailscale-work`. To remove authentication state as well, use `uninstall-legacy-work --purge-state` instead. The host daemon and its current Private account are left unchanged. The original device registration remains in the Work admin console until removed there.

After successful removal, the temporary installer itself can be deleted:

```bash
rm -f /tmp/install-work-tailnet.sh
```

To replace the original setup with a generic instance named `work`, uninstall the legacy setup first, then install `work` using an unused subnet and its actual DNS suffix. Authenticate the new instance again; generic state storage is intentionally separate from legacy state.

## Routing boundaries

Only tailnet destinations and explicitly accepted subnet routes use Tailscale. Ordinary internet access uses the host uplink unless you select an exit node on the isolated daemon. The namespace's uplink rejects direct access to the host and the Tailscale IPv4 range and only forwards through the selected uplink. IPv6 has no external uplink in this implementation.

This provides network routing separation for terminal applications, not a security sandbox against the user. Filesystems and Unix sockets remain accessible; applications can deliberately use host services, custom resolvers, or their own proxy settings. Host LAN access through the uplink is allowed. Host exit-node routing and firewall reloads, including Docker restarts, can interfere with forwarding; restart the namespace service after closing its shells if needed.

## Preview and validation

Render installation files into a local directory without sudo or system changes:

```bash
./tailnet-shell render demo --subnet 10.203.84.0/30 --output .preview
python3 -m unittest discover -s tests -v
```

Tests validate input handling, generated shell syntax, separate instance resources, cleanup after partial startup, refusal to uninstall active shells, and legacy matching. Network commands in cleanup tests are mocked. The generic installer and removal commands require privileged integration testing; the original Work installation was confirmed working by its user.
