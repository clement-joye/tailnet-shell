# Development

[Back to README](../README.md)

## Preview and validation

Render installation files into a local directory without sudo or system changes. Preview requires an explicit subnet so it does not need to inspect host networking:

```bash
./tailnet-shell render demo --subnet 10.203.84.0/30 --output .preview
python3 -m unittest discover -s tests -v
```

Tests validate subnet allocation and exhaustion, route/interface/instance reservations, manual overrides, input handling, generated shell syntax, separate instance resources, cleanup after partial startup, refusal to uninstall active shells, and validation of older installation layouts. They also exercise VPN interface changes, connection-tracking cleanup, loss and recovery of routes, NAT update failures, and upgrades that preserve configuration. Network commands in tests are mocked. Privileged installation, upgrade, and VPN connectivity require integration testing; the earlier installation was confirmed working by its user.
