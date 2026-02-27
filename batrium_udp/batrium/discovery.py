"""
Build Home Assistant MQTT auto-discovery config payloads.

All entities share one state topic and use value_template to extract their field.

Two types of discovery:
  build_discovery_configs()       — pack-level entities, published once on connect
  build_node_discovery_configs()  — per-node entities, published when a new node is first seen

With individual CellMate-K/J hardware (one unit per cell), each node = one cell, so
node_N_volt_min / node_N_volt_max are the individual cell voltages for cell N.
With a K9 board, each node covers all cells on the board (volt_min/max are pack aggregate).

Reference: https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery
"""

import json

DEVICE_MANUFACTURER = "Batrium"
DEVICE_MODEL        = "WatchMon Core"
DEVICE_NAME         = "Batrium"


ADDON_VERSION       = "1.0.0"
ADDON_URL           = "https://github.com/rkflyer/batrium-ha-addon"


def _device(system_name: str, sys_id: int) -> dict:
    return {
        "identifiers":       [f"batrium_{sys_id}"],
        "name":              DEVICE_NAME,
        "manufacturer":      DEVICE_MANUFACTURER,
        "model":             DEVICE_MODEL,
        "sw_version":        f"RKflyer/batrium-ha-addon {ADDON_VERSION}",
        "configuration_url": ADDON_URL,
    }


def _make_sensor(
    uid: str,
    name: str,
    state_topic: str,
    avail_topic: str,
    device: dict,
    field: str,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    icon: str | None = None,
) -> tuple[str, str]:
    payload: dict = {
        "unique_id":          uid,
        "name":               name,
        "state_topic":        state_topic,
        "value_template":     f"{{{{ value_json.{field} }}}}",
        "availability_topic": avail_topic,
        "device":             device,
    }
    if unit:
        payload["unit_of_measurement"] = unit
    if device_class:
        payload["device_class"] = device_class
    if state_class:
        payload["state_class"] = state_class
    if icon:
        payload["icon"] = icon
    return (f"homeassistant/sensor/{uid}/config", json.dumps(payload))


def _make_binary_sensor(
    uid: str,
    name: str,
    state_topic: str,
    avail_topic: str,
    device: dict,
    field: str,
    device_class: str | None = None,
) -> tuple[str, str]:
    # Template to "ON"/"OFF" avoids Python True/False repr ambiguity
    payload: dict = {
        "unique_id":          uid,
        "name":               name,
        "state_topic":        state_topic,
        "value_template":     f"{{% if value_json.{field} %}}ON{{% else %}}OFF{{% endif %}}",
        "payload_on":         "ON",
        "payload_off":        "OFF",
        "availability_topic": avail_topic,
        "device":             device,
    }
    if device_class:
        payload["device_class"] = device_class
    return (f"homeassistant/binary_sensor/{uid}/config", json.dumps(payload))


def build_discovery_configs(system_name: str, sys_id: int) -> list[tuple[str, str]]:
    """
    Pack-level entities derived from 0x3E33 and 0x3F33.
    Published once on MQTT connect (and again on reconnect).
    """
    state_topic = f"batrium/{system_name}/state"
    avail_topic = f"batrium/{system_name}/availability"
    device      = _device(system_name, sys_id)
    configs: list[tuple[str, str]] = []

    def uid(s):
        return f"batrium_{sys_id}_{s}"

    def S(suffix, name, field, **kw):
        configs.append(_make_sensor(uid(suffix), name, state_topic, avail_topic, device, field, **kw))

    def B(suffix, name, field, **kw):
        configs.append(_make_binary_sensor(uid(suffix), name, state_topic, avail_topic, device, field, **kw))

    # --- Pack voltages (from 0x3E33) ---
    S("volt_min",    "Cell Voltage Min",    "volt_min",    unit="mV", device_class="voltage", icon="mdi:lightning-bolt")
    S("volt_max",    "Cell Voltage Max",    "volt_max",    unit="mV", device_class="voltage", icon="mdi:lightning-bolt")
    S("volt_avg",    "Cell Voltage Avg",    "volt_avg",    unit="mV", device_class="voltage", icon="mdi:lightning-bolt")
    S("volt_spread", "Cell Voltage Spread", "volt_spread", unit="mV", icon="mdi:arrow-expand-vertical")

    # --- Temperature (from 0x3E33) ---
    S("temp_min_c", "Cell Temp Min", "temp_min_c", unit="°C", device_class="temperature", icon="mdi:thermometer-low")
    S("temp_max_c", "Cell Temp Max", "temp_max_c", unit="°C", device_class="temperature", icon="mdi:thermometer-high")
    S("temp_avg_c", "Cell Temp Avg", "temp_avg_c", unit="°C", device_class="temperature", icon="mdi:thermometer")

    # --- Shunt telemetry (from 0x3F34 StatusShunt, 300ms) ---
    S("shunt_ma",       "Shunt Current",   "shunt_ma",       unit="mA", device_class="current",  icon="mdi:current-dc")
    S("shunt_watt",     "Pack Power",      "shunt_watt",     unit="W",  device_class="power",    icon="mdi:lightning-bolt")
    S("shunt_volt_mv",  "Pack Voltage",    "shunt_volt_mv",  unit="mV", device_class="voltage",  icon="mdi:battery")
    S("shunt_soc_pct",  "SOC (Coulomb)",   "shunt_soc_pct",  unit="%",  device_class="battery",  icon="mdi:battery-high", state_class="measurement")

    # --- Bypass current (from 0x3E33) ---
    S("min_bypass_ma", "Min Bypass Current",  "min_bypass_ma", unit="mA", icon="mdi:lightning-bolt-circle")
    S("max_bypass_ma", "Peak Bypass Current", "max_bypass_ma", unit="mA", icon="mdi:lightning-bolt-circle")

    # --- SOC (from 0x3F34) ---
    S("soc_pct", "State of Charge", "soc_pct", unit="%", device_class="battery", icon="mdi:battery", state_class="measurement")

    # --- Balancing / cell counts (from 0x3E33) ---
    S("bypass_count",          "Cells Balancing",       "bypass_count",          icon="mdi:scale-balance")
    S("cells_in_system",       "Cells in System",       "cells_in_system",       state_class=None, icon="mdi:counter")
    S("cells_active",          "Cells Active",          "cells_active",          state_class=None, icon="mdi:check-circle-outline")
    S("cells_overdue",         "Cells Overdue",         "cells_overdue",         icon="mdi:alert-circle-outline")
    S("min_bypass_session_ah", "Min Bypass Session",    "min_bypass_session_ah", unit="Ah", icon="mdi:battery-charging")
    S("max_bypass_session_ah", "Max Bypass Session",    "max_bypass_session_ah", unit="Ah", icon="mdi:battery-charging")

    # --- Node count (from 0x4232) ---
    S("nodes_online", "Nodes Online", "nodes_online", icon="mdi:network")

    # --- System status (text, from 0x3F33) ---
    S("op_status",    "System Status",  "op_status_name",    state_class=None, icon="mdi:information-outline")
    S("shunt_status", "Shunt Status",   "shunt_status_name", state_class=None, icon="mdi:current-dc")

    # --- Binary: balancing / contactors / relays ---
    B("balancing_active",  "Balancing Active",  "balancing_active")
    B("contactor_battery", "Battery Contactor", "contactor_batt")
    B("load_contactor",    "Load Contactor",    "load_contactor")
    B("expansion_battery", "Expansion Battery", "expansion_battery_on")
    B("relay_1",           "Relay 1",           "relay_1")
    B("relay_2",           "Relay 2",           "relay_2")
    B("relay_3",           "Relay 3",           "relay_3")
    B("relay_4",           "Relay 4",           "relay_4")

    return configs


def build_node_discovery_configs(
    node_id: int, system_name: str, sys_id: int
) -> list[tuple[str, str]]:
    """
    Per-cell entities, published when a cell/node is first seen.

    With CellMate-K/J or K9 on newer firmware (≥ 2.15), each node = one cell.
    volt_min == volt_max so a single 'cell_N_volt' entity is sufficient.
    State field names use cell_ prefix (e.g. cell_3_volt).
    """
    state_topic = f"batrium/{system_name}/state"
    avail_topic = f"batrium/{system_name}/availability"
    device      = _device(system_name, sys_id)
    configs: list[tuple[str, str]] = []
    n = node_id

    def uid(s):
        return f"batrium_{sys_id}_cell{n}_{s}"

    def S(suffix, name, field, **kw):
        configs.append(_make_sensor(uid(suffix), name, state_topic, avail_topic, device, field, **kw))

    def B(suffix, name, field, **kw):
        configs.append(_make_binary_sensor(uid(suffix), name, state_topic, avail_topic, device, field, **kw))

    label = f"Cell {n}"

    # Single voltage (volt_min == volt_max for single-cell nodes)
    S("volt",          f"{label} Voltage",       f"cell_{n}_volt",          unit="mV", device_class="voltage",     icon="mdi:lightning-bolt")

    # Temperature
    S("temp_c",        f"{label} Temp",           f"cell_{n}_temp_c",        unit="°C", device_class="temperature", icon="mdi:thermometer")
    S("bypass_temp_c", f"{label} Bypass Temp",    f"cell_{n}_bypass_temp_c", unit="°C", device_class="temperature", icon="mdi:thermometer-alert")

    # Bypass / balancing
    S("bypass_ma",  f"{label} Bypass Current", f"cell_{n}_bypass_ma",  unit="mA",  icon="mdi:lightning-bolt-circle")
    S("bypass_mah", f"{label} Bypass Energy",  f"cell_{n}_bypass_mah", unit="mAh", icon="mdi:battery-charging")

    # Status
    S("op_status", f"{label} Status", f"cell_{n}_op_status_name", state_class=None, icon="mdi:information-outline")

    B("in_bypass",  f"{label} In Bypass", f"cell_{n}_in_bypass")
    B("is_overdue", f"{label} Overdue",   f"cell_{n}_is_overdue")

    return configs


def build_node_delete_configs(node_id: int, sys_id: int) -> list[tuple[str, str]]:
    """
    Return (topic, '') pairs to delete old 'node_N' entities from HA.
    Publishing empty retained payload removes the entity from auto-discovery.
    Call on startup to clean up entities created before the cell_ rename.
    """
    n = node_id
    old = [
        ("sensor",        "volt_min"),
        ("sensor",        "volt_max"),
        ("sensor",        "temp_c"),
        ("sensor",        "bypass_temp_c"),
        ("sensor",        "bypass_ma"),
        ("sensor",        "bypass_mah"),
        ("sensor",        "op_status"),
        ("binary_sensor", "in_bypass"),
        ("binary_sensor", "is_overdue"),
    ]
    return [
        (f"homeassistant/{domain}/batrium_{sys_id}_node{n}_{field}/config", "")
        for domain, field in old
    ]
