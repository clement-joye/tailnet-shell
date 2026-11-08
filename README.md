# tailnet-shell

**Use a different Tailscale tailnet in any terminal tab—with one command.**

Keep your usual tailnet on your computer, and open a shell connected to another whenever you need it. Works with Ghostty, tmux, and other terminals. No per-application proxy configuration is needed.

Set up each connection once. After that, just run its shell command.

## Quick start

You need Linux with systemd, Tailscale, Python 3.9+, iproute2, iptables, conntrack, and sudo. IPv4 forwarding must be enabled. See [prerequisites and setup](docs/setup.md#requirements) for the full requirements and forwarding command. Developed on Arch Linux; other firewall configurations may need adjustments.

Clone the repository:

```bash
git clone https://github.com/clement-joye/tailnet-shell.git
cd tailnet-shell
```

Choose any short name for your connection, such as `work`, `lab`, or `vm1`. **`client` below is just an example—replace it with your chosen name throughout the commands.** Names must start with a lowercase letter and contain only lowercase letters, digits, or hyphens, up to 12 characters.

```bash
sudo ./tailnet-shell install client
client-tailscale up
```

Your chosen name becomes the command prefix: if you install `work`, use `work-tailscale up` and `work-shell`; if you install `vm1`, use `vm1-tailscale up` and `vm1-shell`.

Open the login URL and sign in to the tailnet you want this connection to use. Your tailnet may require device approval.

The installer chooses the local IP subnet automatically, configures separate DNS, and starts the connection at boot. The launcher handles `--accept-dns=false` for you.

Using a host VPN such as Proton VPN? The connection follows the effective routed interface as the VPN connects or disconnects. See [VPN behavior and upgrading existing installations](docs/usage.md#vpns-and-changing-networks).

## Everyday use

In the terminal tab where you want the other tailnet:

```bash
client-shell
```

Use SSH, Git, curl, and other terminal tools as usual. Run `exit` to return to the surrounding shell. Other tabs keep using their existing connection.

To check the isolated connection:

```bash
client-tailscale status
```

Use full tailnet DNS names or IP addresses by default. For short names, see [DNS configuration](docs/setup.md#install-an-instance).

Want another connection? Repeat setup with a different name, such as `lab`. You can run several at once. See [tmux and daily-use details](docs/usage.md#daily-use) for pane behavior and shortcuts.

## Uninstall

Close the connection's shells and stop its applications, then run:

```bash
sudo ./tailnet-shell uninstall client
```

Authentication state is kept for reuse. Add `--purge-state` to delete it too. See [removal details](docs/usage.md#uninstall-a-named-instance) for device registration and older installations.

## More details

- [Setup and configuration](docs/setup.md): prerequisites, IP allocation, DNS, and multiple instances.
- [Usage and maintenance](docs/usage.md): tmux, service restarts, uninstalling, and routing boundaries.
- [Development](docs/development.md): preview generated files and run the tests.

This tool separates network routing for shells; it is not a security sandbox. Ordinary internet traffic uses your normal uplink unless you select a Tailscale exit node. See [routing boundaries](docs/usage.md#routing-boundaries).

Licensed under the [MIT License](LICENSE).
