"""
Batrium WatchMon UDP protocol parser.

Source: watchmon-wifi-udp-protocol-v0.5.pdf + WatchMonUdpListener /payload/*.js
All multi-byte integers are little-endian.

Hardware note on cell voltages via UDP:
  - CellMate-K / CellMate-J (one unit per cell): each presents as a separate node.
    With 8 cells you get 8 x 0x4232 messages. node.volt_min == node.volt_max == cell voltage.
  - CellMate K9 (one board for all 8 cells): presents as ONE node.
    volt_min/volt_max in 0x4232 are the pack min/max, not individual cells.
  Individual cell voltages are only available via Batrium's MQTT feature (not yet released).
"""

import struct
import logging

_LOGGER = logging.getLogger(__name__)

HEADER_START = 0x3A   # ':'
HEADER_SEP   = 0x2C   # ','

# Message types
MSG_CELL_NODE        = 0x4232  # Per-node full info; 300ms
MSG_CELL_NODE_STATUS = 0x415A  # All nodes in one packet (array); 300ms — preferred source
MSG_STATUS_RAPID_OLD = 0x3E5A  # Pack stats, SW ≤ 1.0.29; 300ms
MSG_CELL_STATS       = 0x3E33  # Pack stats, SW ≥ 2.15;   300ms
MSG_STATUS_FAST      = 0x3F33  # SOC, relays, contactors (older FW)
MSG_STATUS_SHUNT     = 0x3F34  # ShuntCurrent/Voltage/Power/SOC (FW ≥ 2.15); 300ms

# TODO: decode additional packets for HA energy dashboard integration
#   0x5432  Msg_5432_DailySession     — DailySessionCumulShuntkWhCharge/Dischg, peak currents
#   0x7832  Msg_7832_HwShuntMetrics   — hardware shunt metrics, lifetime totals
#   See: github.com/Batrium/WatchMonUdpListener/tree/master/payload

OP_STATUS_NAMES = {
    0: "Timeout",
    1: "Idle",
    2: "Charging",
    3: "Discharging",
    4: "Full",
    5: "Empty",
    7: "CriticalPending",
    8: "CriticalOffline",
}

NODE_STATUS_NAMES = {
    0: "None",
    1: "HighVolt",
    2: "HighTemp",
    3: "Ok",
    5: "LowVolt",
    7: "InBypass",
    8: "InitialBypass",
    9: "FinalBypass",
}

SHUNT_STATUS_NAMES = {
    0: "Timeout",
    1: "Discharging",
    2: "Idle",
    4: "Charging",
}


def parse_header(data: bytes):
    """
    Parse the 8-byte packet header.
    Returns (msg_type: int, sys_id: int) or None if invalid.
    """
    if len(data) < 8:
        return None
    if data[0] != HEADER_START or data[3] != HEADER_SEP:
        return None
    msg_type = struct.unpack_from("<H", data, 1)[0]
    sys_id   = struct.unpack_from("<H", data, 4)[0]
    return msg_type, sys_id


def parse_4232(data: bytes) -> dict | None:
    """
    Parse Cell Node Full Info (0x4232, 52 bytes, 300ms).

    With individual CellMate-K/J units (one per cell), there is one 0x4232 message
    per cell per broadcast cycle; volt_min == volt_max == that cell's voltage.
    With a K9 board, there is one message covering all cells on the board.
    """
    if len(data) < 52:
        _LOGGER.debug("0x4232 too short: %d bytes", len(data))
        return None
    op = data[20]
    return {
        "node_id":       data[8],
        "volt_min":      struct.unpack_from("<h", data, 10)[0],    # mV
        "volt_max":      struct.unpack_from("<h", data, 12)[0],    # mV
        "temp_c":        data[14] - 40,                             # °C (min cell temp on node)
        "bypass_temp_c": data[15] - 40,                             # °C (bypass resistor temp)
        "bypass_ma":     struct.unpack_from("<h", data, 16)[0],    # mA (0 = not balancing)
        "op_status":     op,
        "op_status_name": NODE_STATUS_NAMES.get(op, f"Unknown({op})"),
        "in_bypass":     op in (7, 8, 9),
        "is_overdue":    bool(data[21]),
        "bypass_mah":    round(struct.unpack_from("<f", data, 47)[0], 2),
    }


def parse_3e33(data: bytes) -> dict | None:
    """
    Parse Cell Stats / Combined Status Rapid (0x3E33 or 0x3E5A, 48 bytes, 300ms).
    0x3E5A is SW ≤ 1.0.29; 0x3E33 is SW ≥ 2.15 — identical field layout.

    Pack-level aggregate across all nodes.
    Source: WatchMonUdpListener/payload/Msg_3e33_StatusCellStats.js

    NOTE: shunt/pack current is NOT in this packet.  It lives in 0x3233 (LiveDisplay)
    or equivalent on newer firmware.  Offset 38 = MinBypassSession (Ah), 42 = MaxBypassSession.
    """
    if len(data) < 48:
        _LOGGER.debug("0x3E33/3E5A too short: %d bytes", len(data))
        return None
    return {
        "volt_min":              struct.unpack_from("<h", data,  8)[0],   # mV
        "volt_max":              struct.unpack_from("<h", data, 10)[0],   # mV
        "temp_min_c":            data[14] - 40,                            # °C
        "temp_max_c":            data[15] - 40,                            # °C
        "temp_avg_c":            data[30] - 40,                            # °C
        "min_bypass_ma":         struct.unpack_from("<h", data, 18)[0],   # mA
        "max_bypass_ma":         struct.unpack_from("<h", data, 20)[0],   # mA peak balancing
        "volt_avg":              struct.unpack_from("<h", data, 28)[0],   # mV
        "bypass_count":          data[33],                                  # cells actively balancing
        "cells_overdue":         data[34],                                  # CMU comms failures
        "cells_active":          data[35],                                  # cells responding
        "cells_in_system":       data[36],                                  # total cell count
        "min_bypass_session_ah": round(struct.unpack_from("<f", data, 38)[0], 3),  # Ah
        "max_bypass_session_ah": round(struct.unpack_from("<f", data, 42)[0], 3),  # Ah
    }


# Same field layout — alias so callers can reference the old message type by name
parse_3e5a = parse_3e33


def parse_415a(data: bytes) -> dict | None:
    """
    Parse Cell Node Status array (0x415A, 100 bytes, 300ms).

    All nodes in a single packet — the preferred source for per-cell voltages.
    With K9 hardware on firmware ≥ ~2.15, the K9 exposes each cell as a
    separate node, so 8S = 8 entries with individual cell voltages.

    Payload layout (after 8-byte packet header):
      [0]     USN / sequence counter
      [1]     cells_in_system
      [2]     unknown (0x01)
      [3]     node_count (number of entries that follow)
      [4 + n*11 + 0]   node_id
      [4 + n*11 + 1]   per-node USN
      [4 + n*11 + 2:4] volt_min  (int16le, mV)
      [4 + n*11 + 4:6] volt_max  (int16le, mV)
      [4 + n*11 + 6]   temp_min  (raw, -40 = °C)
      [4 + n*11 + 7]   temp_max  (raw)
      [4 + n*11 + 8:10] bypass_ma (int16le, mA)
      [4 + n*11 + 10]  op_status
    """
    min_len = 8 + 4  # header + 4-byte array header
    if len(data) < min_len:
        _LOGGER.debug("0x415A too short: %d bytes", len(data))
        return None

    payload      = data[8:]
    cells_in_sys = payload[1]
    node_count   = payload[3]

    if len(payload) < 4 + node_count * 11:
        _LOGGER.debug("0x415A truncated: expected %d bytes payload, got %d",
                      4 + node_count * 11, len(payload))
        return None

    nodes = []
    for i in range(node_count):
        base = 4 + i * 11
        op   = payload[base + 10]
        nodes.append({
            "node_id":    payload[base],
            "volt_min":   struct.unpack_from("<h", payload, base + 2)[0],  # mV
            "volt_max":   struct.unpack_from("<h", payload, base + 4)[0],  # mV
            "temp_min_c": payload[base + 6] - 40,                           # °C
            "temp_max_c": payload[base + 7] - 40,
            "bypass_ma":  struct.unpack_from("<h", payload, base + 8)[0],  # mA
            "op_status":  op,
            "op_status_name": NODE_STATUS_NAMES.get(op, f"Unknown({op})"),
            "in_bypass":  op in (7, 8, 9),
        })

    return {
        "cells_in_system": cells_in_sys,
        "node_count":      node_count,
        "nodes":           nodes,
    }


def parse_3f34(data: bytes) -> dict | None:
    """
    Parse Status Shunt (0x3F34, 50 bytes, 300ms).
    Used by firmware ≥ 2.15 instead of 0x3F33.

    Source: WatchMonUdpListener/payload/Msg_3f34_StatusShunt.js
    All offsets from packet start (including 8-byte header).

      data[12:14]  ShuntVoltage  int16le  /100 = V  (×10 → mV for HA)
      data[14:18]  ShuntCurrent  float32  raw = mA  (+charge, -discharge)
      data[18:22]  ShuntPowerVA  float32  raw = W   (+charge, -discharge)
      data[22:24]  ShuntSOC      int16le  /100 = %  (Coulomb-counted)
      data[24]     WatchMon SOC raw  (raw×0.5)−5 = %
      data[25]     op_status
      data[39:42]  relay_1-3     (tentative, observed all zero)
    """
    if len(data) < 50:
        _LOGGER.debug("0x3F34 too short: %d bytes", len(data))
        return None
    soc_raw   = data[24]
    shunt_ma  = round(struct.unpack_from("<f", data, 14)[0], 1)

    # Derive op_status from shunt current direction (confirmed reliable).
    # data[25] was tentatively mapped to op_status but is unconfirmed — don't use it.
    if shunt_ma < -50:
        op, op_name = 3, "Discharging"
    elif shunt_ma > 50:
        op, op_name = 2, "Charging"
    else:
        op, op_name = 1, "Idle"

    return {
        "op_status":       op,
        "op_status_name":  op_name,
        "soc_pct":         round((soc_raw * 0.5) - 5, 1),   # WatchMon estimate
        "shunt_soc_pct":   round(struct.unpack_from("<h", data, 22)[0] / 100.0, 2),  # Coulomb counted
        "shunt_volt_mv":   struct.unpack_from("<h", data, 12)[0] * 10,  # int16/100=V → ×10=mV
        "shunt_ma":        shunt_ma,                          # mA, negative=discharge positive=charge
        "shunt_watt":      round(struct.unpack_from("<f", data, 18)[0], 1),  # W, same sign
        "relay_1":         bool(data[39]),
        "relay_2":         bool(data[40]),
        "relay_3":         bool(data[41]),
    }


def parse_3f33(data: bytes) -> dict | None:
    """
    Parse Combined Status Fast (0x3F33, 80 bytes, 1.55s).
    SOC, system op status, shunt status, relay and contactor states.
    """
    if len(data) < 62:
        _LOGGER.debug("0x3F33 too short: %d bytes", len(data))
        return None
    soc_raw     = data[32]
    shunt_st    = data[43]
    op          = data[23]
    return {
        "op_status":           op,
        "op_status_name":      OP_STATUS_NAMES.get(op, f"Unknown({op})"),
        "soc_pct":             round((soc_raw * 0.5) - 5, 1),   # raw 10=0%, 200=95%
        "shunt_status":        shunt_st,
        "shunt_status_name":   SHUNT_STATUS_NAMES.get(shunt_st, f"Unknown({shunt_st})"),
        "expansion_battery_on": bool(data[46]),
        "relay_1":             bool(data[50]),
        "relay_2":             bool(data[51]),
        "relay_3":             bool(data[52]),
        "relay_4":             bool(data[53]),
        "contactor_batt":      bool(data[60]),
        "load_contactor":      bool(data[61]),
    }
