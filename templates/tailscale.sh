#!/usr/bin/env bash
set -euo pipefail
client=(sudo /usr/bin/ip netns exec tn-@NAME@ /usr/bin/tailscale --socket=/run/tailnet-shell-@NAME@/tailscaled.sock)
case "${1:-}" in
up|login|set)
  # Help must remain usable without contacting or changing the daemon.
  for argument in "$@"; do
    case "$argument" in -h|--help|-help) exec "${client[@]}" "$@" ;; esac
  done
  for argument in "$@"; do
    case "$argument" in
      --accept-dns=false|-accept-dns=false|--accept-dns=0|-accept-dns=0|--accept-dns=f|-accept-dns=f|--accept-dns=F|-accept-dns=F|--accept-dns=False|-accept-dns=False|--accept-dns=FALSE|-accept-dns=FALSE) ;;
      --accept-dns|--accept-dns=*|-accept-dns|-accept-dns=*)
        echo 'This launcher manages DNS separately; accept-dns must remain false.' >&2
        exit 2 ;;
    esac
  done
  if [[ $1 == up && $# == 1 ]]; then
    # A bare up must retain existing preferences. Injecting a flag would make
    # Tailscale require all nondefault preferences to be specified again.
    configured=$("${client[@]}" debug prefs | python3 -c 'import json,sys; print("yes" if json.load(sys.stdin).get("ControlURL") else "no")')
    if [[ $configured == yes ]]; then
      "${client[@]}" set --accept-dns=false
      exec "${client[@]}" up
    fi
  fi
  if [[ $1 != set || $# != 1 ]]; then
    subcommand=$1
    shift
    exec "${client[@]}" "$subcommand" --accept-dns=false "$@"
  fi
  ;;
esac
exec "${client[@]}" "$@"
