## 1.0.4

- Fix: missing state fields no longer log-spam HA. Auto-discovery templates now use `value_json.get()`, so fields absent from the state JSON (older WatchMon generations that don't transmit 0x3E33/0x3F34, e.g. WatchMon1) render as "unknown" instead of raising a "dict object has no attribute" warning every second. Closes #2.
- Fix: a port conflict at startup (e.g. a Node-RED UDP flow still bound to 18542) now produces an actionable error message explaining how to resolve it, instead of an unhandled `OSError: Address in use` traceback and restart loop. Addresses #3.
- Docs: clarified `udp_port` (the WatchMon transmits to a fixed port; the listener is the only configurable side) and added troubleshooting entries for port conflicts and template warnings.

## 1.0.3

- Fix Pack Voltage reading negative on high-voltage systems (e.g. 48V+ packs). The shunt voltage field was decoded as a signed integer, causing overflow above ~327V. Now correctly decoded as unsigned.

## 1.0.2

- Initial public release.
