#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run this installer with sudo bash.' >&2; exit 1; }
for tool in ip iptables tailscale tailscaled systemctl runuser mount; do
  command -v "$tool" >/dev/null
done
if [[ -e /etc/systemd/system/tailscaled-work.service || -e /etc/systemd/system/work-tailnet-netns.service ]] || ip netns list | awk '{print $1}' | grep -qx ts-work; then
  echo 'Work namespace or services already exist; refusing to overwrite.' >&2
  exit 1
fi
if ip -4 route show table all | grep -q '10\.203\.77\.'; then
  echo 'Chosen namespace subnet is already in use; aborting.' >&2
  exit 1
fi
install -d -m 755 /etc/netns/ts-work /etc/tailscale-work /usr/local/libexec
install -d -m 700 /var/lib/tailscale-work
# The daemon needs ordinary DNS before it can join Work.
printf 'nameserver 1.1.1.1\nnameserver 9.9.9.9\n' >/etc/netns/ts-work/resolv.conf
sed 's/^hosts:.*/hosts: files dns/' /etc/nsswitch.conf >/etc/netns/ts-work/nsswitch.conf
# Work shells use the namespace's own Tailscale DNS resolver.
printf 'nameserver 100.100.100.100\nsearch tail258530.ts.net\n' >/etc/tailscale-work/resolv.conf
cat >/usr/local/libexec/work-tailnet-netns <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
start)
  [[ $(cat /proc/sys/net/ipv4/ip_forward) == 1 ]] || { echo 'IPv4 forwarding must be enabled.' >&2; exit 1; }
  uplink=$(ip -4 route show default | awk 'NR==1 {for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}')
  [[ -n $uplink ]] || { echo 'No default uplink found.' >&2; exit 1; }
  ip netns add ts-work
  ip link add tsw-host type veth peer name tsw-peer
  ip link set tsw-peer netns ts-work
  ip addr add 10.203.77.1/30 dev tsw-host
  ip link set tsw-host up
  ip -n ts-work link set lo up
  ip -n ts-work addr add 10.203.77.2/30 dev tsw-peer
  ip -n ts-work link set tsw-peer up
  ip -n ts-work route add default via 10.203.77.1
  iptables -w -N TSW-FWD
  iptables -w -A TSW-FWD -i tsw-host -d 100.64.0.0/10 -j REJECT
  iptables -w -A TSW-FWD -i tsw-host -o "$uplink" -j ACCEPT
  iptables -w -A TSW-FWD -i tsw-host -j REJECT
  iptables -w -A TSW-FWD -o tsw-host -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -w -A TSW-FWD -o tsw-host -j REJECT
  iptables -w -I FORWARD 1 -j TSW-FWD
  iptables -w -I INPUT 1 -i tsw-host -j REJECT
  iptables -w -t nat -A POSTROUTING -s 10.203.77.2/32 -o "$uplink" -j MASQUERADE
  printf '%s\n' "$uplink" >/run/work-tailnet-uplink
  ;;
stop)
  if [[ -f /run/work-tailnet-uplink ]]; then
    read -r uplink </run/work-tailnet-uplink
    iptables -w -t nat -D POSTROUTING -s 10.203.77.2/32 -o "$uplink" -j MASQUERADE || true
  fi
  iptables -w -D INPUT -i tsw-host -j REJECT || true
  iptables -w -D FORWARD -j TSW-FWD || true
  iptables -w -F TSW-FWD || true
  iptables -w -X TSW-FWD || true
  ip link del tsw-host 2>/dev/null || true
  ip netns del ts-work 2>/dev/null || true
  rm -f /run/work-tailnet-uplink
  ;;
*) exit 2 ;;
esac
SCRIPT
chmod 755 /usr/local/libexec/work-tailnet-netns
cat >/etc/systemd/system/work-tailnet-netns.service <<'UNIT'
[Unit]
Description=Network namespace and uplink for Work Tailscale
Wants=network-online.target
After=network-online.target docker.service
Before=tailscaled-work.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/libexec/work-tailnet-netns start
ExecStop=/usr/local/libexec/work-tailnet-netns stop
ExecStopPost=/bin/sh -c 'if [ "$SERVICE_RESULT" != success ]; then /usr/local/libexec/work-tailnet-netns stop; fi'
UNIT
cat >/etc/systemd/system/tailscaled-work.service <<'UNIT'
[Unit]
Description=Work Tailscale in its own network namespace
Requires=work-tailnet-netns.service
After=work-tailnet-netns.service

[Service]
RuntimeDirectory=tailscale-work
RuntimeDirectoryMode=0755
ExecStart=/usr/bin/ip netns exec ts-work /usr/bin/tailscaled --state=/var/lib/tailscale-work/tailscaled.state --socket=/run/tailscale-work/tailscaled.sock --port=0
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
cat >/usr/local/bin/work-tailscale <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
exec sudo /usr/bin/ip netns exec ts-work /usr/bin/tailscale --socket=/run/tailscale-work/tailscaled.sock "$@"
SCRIPT
cat >/usr/local/bin/work-shell <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID != 0 ]]; then
  exec sudo /usr/local/bin/work-shell
fi
user=${SUDO_USER:?Run work-shell as your normal user}
[[ $user != root ]] || exit 1
shell=$(getent passwd "$user" | cut -d: -f7)
exec /usr/bin/ip netns exec ts-work /bin/bash -c '
  mount --bind /etc/tailscale-work/resolv.conf /etc/resolv.conf
  exec runuser -u "$1" -- env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy WORK_TAILNET=1 "$2" -l
' bash "$user" "$shell"
SCRIPT
chmod 755 /usr/local/bin/work-shell /usr/local/bin/work-tailscale
systemctl daemon-reload
systemctl enable --now tailscaled-work.service
echo 'Installed. Next: work-tailscale up --accept-dns=false --hostname=archlinux-work-tab'
