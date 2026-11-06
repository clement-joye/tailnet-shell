#!/usr/bin/env bash
set -euo pipefail
namespace=tn-@NAME@
host=tn@TOKEN@h
peer=tn@TOKEN@p
chain=TN_@TOKEN@
runtime=/run/tailnet-shell-@NAME@
case "${1:-}" in
start)
  [[ $(cat /proc/sys/net/ipv4/ip_forward) == 1 ]] || { echo 'Enable IPv4 forwarding first.' >&2; exit 1; }
  uplink=$(ip -4 route show default | awk 'NR==1 {for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}')
  [[ -n $uplink ]] || { echo 'No default uplink found.' >&2; exit 1; }
  # Record this before mutations so a partial start can be cleaned up.
  printf '%s\n' "$uplink" >"$runtime/uplink"
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
  iptables -w -A "$chain" -i "$host" -o "$uplink" -j ACCEPT
  iptables -w -A "$chain" -i "$host" -j REJECT
  iptables -w -A "$chain" -o "$host" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -w -A "$chain" -o "$host" -j REJECT
  iptables -w -I FORWARD 1 -j "$chain"
  iptables -w -I INPUT 1 -i "$host" -j REJECT
  iptables -w -t nat -A POSTROUTING -s @ADDRESS@/32 -o "$uplink" -j MASQUERADE
  ;;
stop)
  if [[ -f $runtime/uplink ]]; then
    read -r uplink <"$runtime/uplink"
    if iptables -w -t nat -C POSTROUTING -s @ADDRESS@/32 -o "$uplink" -j MASQUERADE 2>/dev/null; then
      iptables -w -t nat -D POSTROUTING -s @ADDRESS@/32 -o "$uplink" -j MASQUERADE
    fi
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
*) echo 'Expected start or stop' >&2; exit 2 ;;
esac
