#!/usr/bin/env bash
set -euo pipefail
namespace=tn-@NAME@
host=tn@TOKEN@h
peer=tn@TOKEN@p
chain=TN_@TOKEN@
nat_chain=TN_@TOKEN@_NAT
runtime=/run/tailnet-shell-@NAME@
# Query a forwarded packet, including its source and incoming veth, so Linux
# applies the same policy routing rules used by VPNs. This sends no packets.
refresh_uplink() {
  local uplink previous connections
  uplink=$(ip -4 route get 1.1.1.1 from @ADDRESS@ iif "$host" 2>/dev/null |
    awk 'NR==1 {for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}') || uplink=
  case "$uplink" in tailscale0|lo|"$host") uplink= ;; esac
  previous=$(cat "$runtime/uplink" 2>/dev/null) || previous=
  if [[ -f $runtime/uplink && $uplink == "$previous" ]]; then return; fi

  # Close forwarding before replacing NAT; never allow an interface with stale
  # NAT, and never fall back to the physical uplink if policy routing fails.
  iptables -w -R "$chain" 2 -i "$host" -j REJECT
  # Established flows otherwise retain the old interface's source NAT address.
  # Limit conntrack changes to traffic originating from this namespace.
  connections=$(conntrack -L -f ipv4 -s @ADDRESS@)
  if [[ -n $connections ]]; then
    conntrack -D -f ipv4 -s @ADDRESS@
  fi
  iptables -w -t nat -F "$nat_chain"
  if [[ -n $uplink ]]; then
    iptables -w -t nat -A "$nat_chain" -o "$uplink" -j MASQUERADE
    iptables -w -R "$chain" 2 -i "$host" -o "$uplink" -j ACCEPT
    echo "Namespace $namespace now uses $uplink"
  else
    echo "Namespace $namespace has no eligible uplink; forwarding blocked"
  fi
  printf '%s\n' "$uplink" >"$runtime/uplink"
}

case "${1:-}" in
start)
  [[ $(cat /proc/sys/net/ipv4/ip_forward) == 1 ]] || { echo 'Enable IPv4 forwarding first.' >&2; exit 1; }
  ip netns add "$namespace"
  ip link add "$host" type veth peer name "$peer"
  ip link set "$peer" netns "$namespace"
  ip addr add @GATEWAY@/30 dev "$host"
  ip link set "$host" up
  ip -n "$namespace" link set lo up
  ip -n "$namespace" addr add @ADDRESS@/30 dev "$peer"
  ip -n "$namespace" link set "$peer" up
  ip -n "$namespace" route add default via @GATEWAY@
  iptables -w -N "$chain"
  iptables -w -A "$chain" -i "$host" -d 100.64.0.0/10 -j REJECT
  # Rule 2 is replaced when the effective uplink changes.
  iptables -w -A "$chain" -i "$host" -j REJECT
  iptables -w -A "$chain" -i "$host" -j REJECT
  iptables -w -A "$chain" -o "$host" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -w -A "$chain" -o "$host" -j REJECT
  iptables -w -I FORWARD 1 -j "$chain"
  iptables -w -I INPUT 1 -i "$host" -j REJECT
  iptables -w -t nat -N "$nat_chain"
  iptables -w -t nat -A POSTROUTING -s @ADDRESS@/32 -j "$nat_chain"
  refresh_uplink
  ;;
refresh)
  refresh_uplink
  ;;
watch)
  while true; do
    refresh_uplink
    sleep 2
  done
  ;;
stop)
  if [[ -f $runtime/uplink ]]; then
    read -r uplink <"$runtime/uplink"
    if iptables -w -t nat -C POSTROUTING -s @ADDRESS@/32 -o "$uplink" -j MASQUERADE 2>/dev/null; then
      iptables -w -t nat -D POSTROUTING -s @ADDRESS@/32 -o "$uplink" -j MASQUERADE
    fi
  fi
  if iptables -w -t nat -C POSTROUTING -s @ADDRESS@/32 -j "$nat_chain" 2>/dev/null; then
    iptables -w -t nat -D POSTROUTING -s @ADDRESS@/32 -j "$nat_chain"
  fi
  if iptables -w -t nat -S "$nat_chain" >/dev/null 2>&1; then
    iptables -w -t nat -F "$nat_chain"
    iptables -w -t nat -X "$nat_chain"
  fi
  if iptables -w -C INPUT -i "$host" -j REJECT 2>/dev/null; then
    iptables -w -D INPUT -i "$host" -j REJECT
  fi
  if iptables -w -C FORWARD -j "$chain" 2>/dev/null; then
    iptables -w -D FORWARD -j "$chain"
  fi
  if iptables -w -S "$chain" >/dev/null 2>&1; then
    iptables -w -F "$chain"
    iptables -w -X "$chain"
  fi
  if ip link show "$host" >/dev/null 2>&1; then ip link del "$host"; fi
  if ip netns list | awk '{print $1}' | grep -qx "$namespace"; then ip netns del "$namespace"; fi
  rm -f "$runtime/uplink"
  ;;
*) echo 'Expected start, refresh, watch, or stop' >&2; exit 2 ;;
esac
