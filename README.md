# Batrium UDP — Home Assistant Addon

Listens for Batrium WatchMon UDP broadcasts on your local network and publishes all battery telemetry to Home Assistant via MQTT auto-discovery. No manual HA configuration required — a **Batrium** device appears automatically with all entities.

## Requirements

- Batrium WatchMon on the same network as Home Assistant (UDP broadcast port 18542)
- An MQTT broker — either the [Mosquitto addon](https://github.com/home-assistant/addons/tree/master/mosquitto) or an external broker

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click ⋮ (top right) → **Repositories**
3. Add: `https://github.com/rkflyer/batrium-ha-addon`
4. Find **Batrium UDP** in the store and click **Install**
5. Go to the **Configuration** tab, fill in your MQTT details, then **Start**

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `mqtt_host` | `core-mosquitto` | MQTT broker hostname or IP. Use `core-mosquitto` for the HA Mosquitto addon, or your broker's IP for an external broker |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_username` | _(empty)_ | MQTT username — leave blank if your broker has no authentication |
| `mqtt_password` | _(empty)_ | MQTT password |
| `udp_port` | `18542` | Batrium UDP broadcast port — don't change unless you have a specific reason |
| `system_name` | `van` | Slug used in MQTT topic names: `batrium/{system_name}/state`. Change this if you have multiple Batrium systems on the same broker |
| `log_level` | `info` | Logging verbosity: `debug`, `info`, `warning`, `error` |

### Using an external MQTT broker

If your MQTT broker is not the HA Mosquitto addon (e.g. running on a NAS, a router, or a separate server):

```yaml
mqtt_host: 192.168.1.100   # IP or hostname of your broker
mqtt_port: 1883
mqtt_username: myuser      # leave blank if no auth required
mqtt_password: mypassword
```

The addon will automatically reconnect if the broker is temporarily unavailable.

## Entities

All entities appear under a single **Batrium** device in HA → Settings → Devices.

### Pack-level (always present)

| Entity | Unit | Notes |
|--------|------|-------|
| Cell Voltage Min / Max / Avg | mV | Pack-wide aggregate |
| Cell Voltage Spread | mV | Max − Min, imbalance indicator |
| Cell Temp Min / Max / Avg | °C | |
| Pack Voltage | mV | From shunt |
| Shunt Current | mA | Positive = charging, negative = discharging |
| Pack Power | W | Positive = charging, negative = discharging |
| State of Charge | % | WatchMon estimate |
| SOC (Coulomb) | % | Coulomb-counted SOC |
| System Status | text | Idle / Charging / Discharging — derived from shunt current |
| Cells Balancing | count | |
| Cells Active / In System | count | |
| Min / Peak Bypass Current | mA | Balancing current |
| Relay 1 / 2 / 3 | on/off | |
| Balancing Active | on/off | True if any cell is balancing |

### Per-cell (appear as cells are discovered, within ~1s of start)

| Entity | Unit |
|--------|------|
| Cell N Voltage | mV |
| Cell N Temp | °C |
| Cell N Bypass Current | mA |
| Cell N Status | text |
| Cell N In Bypass | on/off |

## Hardware notes

- **CellMate-K / CellMate-J** (one unit per cell): each cell appears as a separate node. Cell N Voltage = that cell's exact voltage.
- **CellMate K9** (one board, multiple cells): on firmware ≥ 2.15, the K9 exposes each cell as a separate node with individual voltages.

## Why UDP and not MQTT?

Batrium announced native MQTT publishing in March 2024. As of early 2025 it remains unreleased. UDP broadcast on port 18542 is always-on and requires no WatchMon configuration — it's what every community integration uses. This addon gives you everything available via UDP today.

## Supported architectures

`aarch64` (HA Green, Pi 4/5) · `amd64` (VM, NUC, x86) · `armv7` (Pi 3) · `armhf` (Pi 2) · `i386`

## MQTT topics

| Topic | Content |
|-------|---------|
| `batrium/{system_name}/state` | JSON state payload, published ~1/s |
| `batrium/{system_name}/availability` | `online` / `offline` (last-will) |
| `homeassistant/sensor/{uid}/config` | Auto-discovery configs (retained) |
| `homeassistant/binary_sensor/{uid}/config` | Auto-discovery configs (retained) |

## Local development / testing

Requires Python 3.10+ and `paho-mqtt`.

```bash
cd batrium_udp/
pip install -r requirements.txt

# Override config via environment variables
MQTT_HOST=192.168.1.10 MQTT_USERNAME=user MQTT_PASSWORD=pass SYSTEM_NAME=van \
    python3 batrium/main.py

# Watch what's published
mosquitto_sub -h 192.168.1.10 -u user -P pass -t 'batrium/#' -v
```

## Troubleshooting

**No entities appear**
- Check the addon log — it logs every discovered node and MQTT connection status
- Verify the WatchMon is broadcasting: on a machine on the same network, run:
  ```bash
  python3 -c "
  import socket
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  s.bind(('', 18542))
  print(s.recvfrom(256))
  "
  ```
  If nothing arrives within a few seconds, the WatchMon isn't reachable on that network.

**Entities show "Unavailable"**
- The addon stopped or lost MQTT connection — check the addon log
- Entities recover automatically when the addon reconnects

**MQTT connection refused**
- Check `mqtt_host`, `mqtt_port`, credentials
- If using an external broker, ensure port 1883 is reachable from the HA host

## License

MIT
