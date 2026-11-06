#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID != 0 ]]; then exec sudo /usr/local/bin/@NAME@-shell; fi
user=${SUDO_USER:?Run @NAME@-shell as your normal user}
[[ $user != root ]] || exit 1
shell=$(getent passwd "$user" | cut -d: -f7)
# ip netns exec creates a private mount namespace. Bind shell-only DNS here;
# the daemon keeps bootstrap DNS for control-plane access before authentication.
exec /usr/bin/ip netns exec tn-@NAME@ /bin/bash -c '
  mount --bind /etc/tailnet-shell/@NAME@/resolv.shell /etc/resolv.conf
  exec runuser -u "$1" -- env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy TAILNET_NAMESPACE=@NAME@ "$2" -l
' bash "$user" "$shell"
