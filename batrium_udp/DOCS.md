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
The UDP port Batrium broadcasts on. Default: `18542`. Do not change unless you have a specific reason.

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
