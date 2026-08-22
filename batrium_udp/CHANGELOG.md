## 1.0.6

- Fix: an MQTT connection the broker refuses is now explained instead of numbered. `MQTT connect failed (rc=5)` becomes "the broker refused the connection as not authorised", plus what to check — `rc=4` and `rc=5` mean the credentials were rejected, and with the Mosquitto addon that is almost always a blank or non-existent `mqtt_username`/`mqtt_password`.
- Fix: the addon no longer claims to have published entities it has not published. Discovery configs for a newly-seen node are queued when MQTT is down (correct, and unchanged) but were logged as "published ... entities" regardless. An addon that had never once reached the broker still produced a log full of apparent success, so the visible symptom pointed at the Batrium side while the real fault was the broker.
- Add: while data is arriving and MQTT has never connected, the addon says so — "Receiving Batrium data, but MQTT has never connected — NOTHING has reached Home Assistant". It repeats every 5 minutes rather than firing once, because whoever is debugging pastes an arbitrary slice of the log and the reason needs to be in it.
- Internal: a refused connect logged twice per retry (once from the connect callback, once from the disconnect callback that follows it). The second is now debug-level; the first says everything useful.

## 1.0.5

- Add: the log now names each Batrium message type the first time it arrives — `Receiving 0x3E33 PackStats (48 bytes)`. Which messages a WatchMon transmits varies by generation and firmware, and until now an entity that never populated looked the same whether the data was never sent, arrived too short to decode, or arrived in a message type this addon does not recognise. One line per type at startup, at the default log level, tells you which.
- Add: a message that arrives too short to decode, or in an unrecognised type, is now reported as a warning asking you to raise an issue. Previously both were discarded at debug level, so a WatchMon whose data was being dropped was indistinguishable from one that sent nothing.
- Internal: minimum packet lengths moved to `protocol.MIN_LEN`, so the parsers and the log report against the same numbers.

## 1.0.4

- Fix: missing state fields no longer log-spam HA. Auto-discovery templates now use `value_json.get()`, so fields absent from the state JSON (older WatchMon generations that don't transmit 0x3E33/0x3F34, e.g. WatchMon1) render as "unknown" instead of raising a "dict object has no attribute" warning every second. Closes #2.
- Fix: a port conflict at startup (e.g. a Node-RED UDP flow still bound to 18542) now produces an actionable error message explaining how to resolve it, instead of an unhandled `OSError: Address in use` traceback and restart loop. Addresses #3.
- Docs: clarified `udp_port` (the WatchMon transmits to a fixed port; the listener is the only configurable side) and added troubleshooting entries for port conflicts and template warnings.

## 1.0.3

- Fix Pack Voltage reading negative on high-voltage systems (e.g. 48V+ packs). The shunt voltage field was decoded as a signed integer, causing overflow above ~327V. Now correctly decoded as unsigned.

## 1.0.2

- Initial public release.
