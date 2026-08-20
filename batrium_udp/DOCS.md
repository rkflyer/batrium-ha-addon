# Batrium UDP — Configuration

## Requirements

- Batrium WatchMon on the same network as Home Assistant
- An MQTT broker (the [Mosquitto addon](https://github.com/home-assistant/addons/tree/master/mosquitto) is recommended)

## Configuration options

### `mqtt_host`
Hostname or IP of your MQTT broker.
- If using the **Mosquitto addon**: leave as `core-mosquitto`
- If using an **external broker**: enter its IP address or hostname (e.g. `192.168.1.100`)

### `mqtt_port`
MQTT broker port. Default: `1883`. Only change if your broker uses a non-standard port.

### `mqtt_username` / `mqtt_password`
MQTT credentials. Leave blank if your broker does not require authentication.

### `udp_port`
The UDP port this addon *listens* on for WatchMon broadcasts. Default: `18542`.
Important: the WatchMon always *sends* to 18542 — that is fixed in firmware
and cannot be configured on the device. So only change this option if you have
deliberately reconfigured your WatchMon's broadcast destination (advanced) or
are running multiple addons that must not collide. If the addon fails to start
with "port already in use", the fix is to stop the other listener (e.g. a
Node-RED UDP flow), not to change this port.

### `system_name`
A short slug used in MQTT topic names: `batrium/{system_name}/state`.
Default: `bms`. Only change this if you have multiple Batrium systems on the same MQTT broker — give each a unique name.

### `log_level`
Logging verbosity. `info` is recommended for normal use. Use `debug` if troubleshooting.

## After starting

Within a few seconds of starting, the addon log should show:

```
MQTT connected to ...
Published 239 discovery configs
New node discovered via 0x415A: id=1 — published 8 entities
...
```

A **Batrium** device will appear automatically in **Settings → Devices & Services → Devices** with all battery entities populated. No manual HA configuration is needed.

## Troubleshooting

**No entities appear / MQTT not connecting**
Check the addon log for connection errors. Verify `mqtt_host` and credentials are correct.

**Entities show "Unavailable"**
The addon stopped or lost MQTT connection. Check the log and restart the addon if needed.

**No nodes discovered**
The WatchMon is not reachable on this network. Confirm the WatchMon and HA are on the same subnet.

**Addon crashes on start with "port ... is already in use"**
Another program is listening on the UDP port (usually 18542) — commonly a
Node-RED UDP flow that used to do this job. Stop or disable that flow (or any
other Batrium/WatchMon UDP listener); this addon replaces it, and two
listeners cannot share the same port. See the `udp_port` note above — changing
the port here does not help, because the WatchMon transmits to a fixed port.

**Many "Template variable warning: 'dict object' has no attribute ..." messages in the HA log**
Some fields are missing from the state JSON because your WatchMon firmware does
not transmit the message types those entities come from (older WatchMon
generations, e.g. WatchMon1, only send per-cell messages). Since 1.0.4 the
addon's templates tolerate missing fields: the affected entities simply show
"unknown" and no warning is logged. Upgrading the WatchMon (with an IsoMon)
restores the full entity set.
