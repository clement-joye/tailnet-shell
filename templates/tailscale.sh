#!/usr/bin/env bash
set -euo pipefail
exec sudo /usr/bin/ip netns exec tn-@NAME@ /usr/bin/tailscale --socket=/run/tailnet-shell-@NAME@/tailscaled.sock "$@"
