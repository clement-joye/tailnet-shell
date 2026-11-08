# Usage and maintenance

[Back to README](../README.md)

## Daily use

Run `client-shell` in a Ghostty tab to enter that tailnet. Run `exit` to return to the surrounding shell. Child processes inherit the namespace; new tabs must enter it explicitly. The shell exports `TAILNET_NAMESPACE=client` for optional prompt customization and clears standard HTTP/SOCKS proxy variables.

Use `client-tailscale` to inspect or configure the isolated daemon. Plain `tailscale` still targets the host daemon, even inside the isolated shell, because its Unix socket remains visible.

The launcher supplies `--accept-dns=false` automatically for authentication (`up` or `login`) and preference changes (`set`). It rejects attempts to enable DNS acceptance, since this tool manages DNS separately. A plain `up` on an already configured instance first disables DNS acceptance with `set`, then runs `up` without flags to preserve other saved preferences. Help and read-only commands pass through without changing preferences. Existing installed launchers are not automatically updated by a repository change.

The daemon starts at boot. Its uplink service automatically refreshes forwarding and NAT when the effective network interface changes; see [VPNs and changing networks](#vpns-and-changing-networks).

For tmux, enter the namespace explicitly in every pane, for example:

```tmux
bind-key C new-window -n client 'client-shell'
```

Alternatively start a dedicated tmux server inside the namespace using a distinct socket (`tmux -L client new-session`). Attaching to an existing host tmux server does not move its panes into the namespace.

## VPNs and changing networks

The namespace follows the host's policy-routed internet connection, including VPN interfaces such as Proton VPN's `proton0`. The helper performs a route lookup for a forwarded packet with the instance's source address and incoming virtual interface, instead of assuming that the main routing table's default route is the active connection. The lookup does not send a packet.

A small systemd service checks the effective interface every two seconds. On change, it blocks outgoing forwarding while replacing the instance's NAT rule and deleting stale connection-tracking entries for its source address. It then permits the new interface. There can be a short interruption during VPN connection or disconnection; existing application sessions may need to reconnect. No namespace restart or new Tailscale login is required for an ordinary interface change.

If no route exists, forwarding stays blocked. The helper does not fall back to Wi-Fi, add bypass routes, change VPN marks, or edit the VPN's own firewall rules. Provider-specific firewall or kill-switch policies may still block forwarded traffic. This is not a guarantee of compatibility with every VPN or kill switch.

The interface is selected using a route lookup toward `1.1.1.1`. A split VPN that routes different destinations through different interfaces may need additional integration; this tool permits one outgoing interface per instance. A route through the host's `tailscale0` is blocked to keep the host and isolated tailnets separate. Host Tailscale exit-node routing is therefore unsupported. IPv6 still has no external uplink.

Inspect the detected interface and watcher logs:

```bash
cat /run/tailnet-shell-client/uplink
journalctl -u tailnet-shell-client-uplink.service -n 30 --no-pager
```

If a firewall reload or Docker restart removes the instance's rules, close its shells and stop its applications, then rebuild the namespace:

```bash
sudo systemctl restart tailnet-shell-client-netns.service
```

## Upgrading an instance

Existing installed helpers are not changed by `git pull`. Install the new `conntrack` dependency if needed (see [requirements](setup.md#requirements)), exit the instance's shells, and stop its applications. Then run:

```bash
git pull --ff-only
sudo ./tailnet-shell upgrade client
client-shell
```

Replace `client` with the existing instance name. Upgrade stops the old services before replacing their helpers, so the old cleanup code can remove its rules. It updates scripts and systemd units and starts the instance again. Authentication state, subnet, DNS files, metadata, and the existing boot enablement setting are retained. Custom changes to installed scripts and units are overwritten. Upgrade refuses to proceed while instance shells or applications remain open.

This command supports managed installations with `/etc/tailnet-shell/NAME/instance.json`. For the older layout without metadata, use the [older installation removal](#remove-an-older-installation) procedure first.

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

## Remove an older installation

For instances created with the earlier installer layout, pass the instance name explicitly:

```bash
sudo ./tailnet-shell uninstall-legacy client
```

Use the name of your existing instance in place of `client`. Exit all of its shells and stop its applications first. This compatibility command recognizes the older `ts-NAME` namespace, `tailscaled-NAME.service`, `NAME-tailnet-netns.service`, and `NAME-shell` / `NAME-tailscale` launchers. It checks that installed scripts and units are regular, root-owned files with expected instance-specific layout markers before invoking their existing cleanup helper.

The command removes services, launchers, namespace configuration, and the virtual link and firewall rules handled by the existing cleanup helper. It preserves authentication state under `/var/lib/tailscale-NAME`, unless `--purge-state` is supplied. The host daemon is left unchanged.

The compatibility command does not delete the original installer file; you can delete that file yourself after successful removal. To replace an older installation with the current layout, uninstall the older instance first and install the same or a different name using `install`. Authenticate the new instance again; its state storage is separate.

## Routing boundaries

Only tailnet destinations and explicitly accepted subnet routes use Tailscale. Ordinary internet access uses the host uplink unless you select an exit node on the isolated daemon. The namespace's uplink rejects direct access to the host and the Tailscale IPv4 range and only forwards through the selected uplink. IPv6 has no external uplink in this implementation.

This provides network routing separation for terminal applications, not a security sandbox against the user. Filesystems and Unix sockets remain accessible; applications can deliberately use host services, custom resolvers, or their own proxy settings. Host LAN access through the selected uplink is allowed. See [VPN behavior](#vpns-and-changing-networks) for policy-routing limits, kill-switch considerations, and recovery after firewall reloads.
