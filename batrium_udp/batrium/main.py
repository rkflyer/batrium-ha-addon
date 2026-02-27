"""
Batrium WatchMon UDP → MQTT bridge for Home Assistant.

Binds UDP port 18542, parses Batrium broadcast packets, publishes to MQTT
with Home Assistant auto-discovery (no manual HA configuration needed).

Per-node voltage entities are dynamically created when new nodes are first seen:
  - CellMate-K/J (one unit per cell): node N = cell N; node_N_volt_min/max = cell voltage
  - CellMate K9 (all cells on one board): one node = pack aggregate min/max

Run as HA addon:  /app/run.sh (reads /data/options.json)
Run for local dev: python3 batrium/main.py  (uses env vars or defaults)
"""

import asyncio
import json
import logging
import os
import sys

# Allow running as a script: `python3 batrium/main.py`
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from batrium.protocol import (  # noqa: E402
    parse_header,
    parse_4232,
    parse_415a,
    parse_3e33,
    parse_3f33,
    parse_3f34,
    MSG_CELL_NODE,
    MSG_CELL_NODE_STATUS,
    MSG_STATUS_RAPID_OLD,
    MSG_CELL_STATS,
    MSG_STATUS_FAST,
    MSG_STATUS_SHUNT,
    NODE_STATUS_NAMES,
)
from batrium.discovery import (  # noqa: E402
    build_discovery_configs,
    build_node_discovery_configs,
    build_node_delete_configs,
)
from batrium.publisher import BatriumPublisher  # noqa: E402


def load_config() -> dict:
    """
    Load addon options.

    Priority (highest first):
    1. Environment variables (upper-cased key names) — for local dev
    2. /data/options.json — provided by HA Supervisor
    3. Built-in defaults
    """
    cfg = {
        "mqtt_host":     "core-mosquitto",
        "mqtt_port":     1883,
        "mqtt_username": "",
        "mqtt_password": "",
        "udp_port":      18542,
        "system_name":   "Stanley",
        "log_level":     "info",
    }

    options_path = "/data/options.json"
    if os.path.exists(options_path):
        with open(options_path) as f:
            cfg.update(json.load(f))

    for key, default in cfg.items():
        env_val = os.environ.get(key.upper())
        if env_val is not None:
            cfg[key] = int(env_val) if isinstance(default, int) else env_val

    return cfg


class BatriumUdpProtocol(asyncio.DatagramProtocol):
    """
    asyncio UDP protocol: parses incoming Batrium broadcast packets and pushes
    parsed values into the publisher's state dict.

    On first sight of a new node_id (from 0x4232), publishes per-node MQTT
    auto-discovery configs so HA immediately creates entities for that node.
    """

    def __init__(self, publisher: BatriumPublisher, system_name: str, sys_id: int):
        self._publisher    = publisher
        self._system_name  = system_name
        self._sys_id       = sys_id
        self._seen_nodes: set[int] = set()

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 8:
            return
        header = parse_header(data)
        if not header:
            return
        msg_type, _sys_id = header

        if msg_type == MSG_CELL_NODE_STATUS:
            # Preferred: all cells in one atomic snapshot
            self._handle_415a(data)

        elif msg_type == MSG_CELL_NODE:
            # Fallback / also triggers per-node discovery
            self._handle_4232(data)

        elif msg_type in (MSG_CELL_STATS, MSG_STATUS_RAPID_OLD):
            self._handle_3e33(data)

        elif msg_type in (MSG_STATUS_FAST, MSG_STATUS_SHUNT):
            self._handle_3f3x(data, msg_type)

    def _handle_415a(self, data: bytes) -> None:
        parsed = parse_415a(data)
        if not parsed:
            return

        state_updates = {}
        for node in parsed["nodes"]:
            n = node["node_id"]

            # Publish discovery for newly-seen nodes
            if n not in self._seen_nodes:
                self._seen_nodes.add(n)
                node_configs = build_node_discovery_configs(
                    n, self._system_name, self._sys_id
                )
                self._publisher.publish_node_discovery(node_configs)
                logging.getLogger(__name__).info(
                    "New node discovered via 0x415A: id=%d — published %d entities",
                    n, len(node_configs),
                )

            state_updates.update({
                f"cell_{n}_volt":           node["volt_min"],   # volt_min == volt_max for single-cell nodes
                f"cell_{n}_temp_c":         node["temp_min_c"],
                f"cell_{n}_bypass_ma":      node["bypass_ma"],
                f"cell_{n}_op_status_name": node["op_status_name"],
                f"cell_{n}_in_bypass":      node["in_bypass"],
            })

        state_updates["nodes_online"] = len(self._seen_nodes)
        self._publisher.update_state(state_updates)

    def _handle_4232(self, data: bytes) -> None:
        parsed = parse_4232(data)
        if not parsed:
            return

        node_id = parsed["node_id"]

        # On first sight of this node: publish per-node discovery configs
        if node_id not in self._seen_nodes:
            self._seen_nodes.add(node_id)
            node_configs = build_node_discovery_configs(
                node_id, self._system_name, self._sys_id
            )
            self._publisher.publish_node_discovery(node_configs)
            logging.getLogger(__name__).info(
                "New node discovered: id=%d — published %d discovery entities",
                node_id, len(node_configs),
            )

        # Flatten per-cell fields into state with cell_{id}_ prefix
        n = node_id
        self._publisher.update_state({
            f"cell_{n}_volt":           parsed["volt_min"],   # volt_min == volt_max for single-cell nodes
            f"cell_{n}_temp_c":         parsed["temp_c"],
            f"cell_{n}_bypass_temp_c":  parsed["bypass_temp_c"],
            f"cell_{n}_bypass_ma":      parsed["bypass_ma"],
            f"cell_{n}_bypass_mah":     parsed["bypass_mah"],
            f"cell_{n}_op_status_name": parsed["op_status_name"],
            f"cell_{n}_in_bypass":      parsed["in_bypass"],
            f"cell_{n}_is_overdue":     parsed["is_overdue"],
            "nodes_online":             len(self._seen_nodes),
        })

    def _handle_3e33(self, data: bytes) -> None:
        parsed = parse_3e33(data)
        if not parsed:
            return
        spread = parsed["volt_max"] - parsed["volt_min"]
        self._publisher.update_state({
            "volt_min":              parsed["volt_min"],
            "volt_max":              parsed["volt_max"],
            "volt_avg":              parsed["volt_avg"],
            "volt_spread":           spread,
            "temp_min_c":            parsed["temp_min_c"],
            "temp_max_c":            parsed["temp_max_c"],
            "temp_avg_c":            parsed["temp_avg_c"],
            "min_bypass_ma":         parsed["min_bypass_ma"],
            "max_bypass_ma":         parsed["max_bypass_ma"],
            "bypass_count":          parsed["bypass_count"],
            "cells_overdue":         parsed["cells_overdue"],
            "cells_active":          parsed["cells_active"],
            "cells_in_system":       parsed["cells_in_system"],
            "min_bypass_session_ah": parsed["min_bypass_session_ah"],
            "max_bypass_session_ah": parsed["max_bypass_session_ah"],
            "balancing_active":      parsed["bypass_count"] > 0,
        })

    def _handle_3f3x(self, data: bytes, msg_type: int) -> None:
        if msg_type == MSG_STATUS_SHUNT:
            parsed = parse_3f34(data)
            if not parsed:
                return
            # 0x3F34 = StatusShunt (FW ≥ 2.15): shunt telemetry + SOC + op_status
            self._publisher.update_state({
                "op_status":      parsed["op_status"],
                "op_status_name": parsed["op_status_name"],
                "soc_pct":        parsed["soc_pct"],
                "shunt_soc_pct":  parsed["shunt_soc_pct"],
                "shunt_volt_mv":  parsed["shunt_volt_mv"],
                "shunt_ma":       parsed["shunt_ma"],
                "shunt_watt":     parsed["shunt_watt"],
                "relay_1":        parsed["relay_1"],
                "relay_2":        parsed["relay_2"],
                "relay_3":        parsed["relay_3"],
            })
            return

        parsed = parse_3f33(data)
        if not parsed:
            return
        self._publisher.update_state({
            "op_status":            parsed["op_status"],
            "op_status_name":       parsed["op_status_name"],
            "soc_pct":              parsed["soc_pct"],
            "shunt_status":         parsed["shunt_status"],
            "shunt_status_name":    parsed["shunt_status_name"],
            "expansion_battery_on": parsed["expansion_battery_on"],
            "relay_1":              parsed["relay_1"],
            "relay_2":              parsed["relay_2"],
            "relay_3":              parsed["relay_3"],
            "relay_4":              parsed["relay_4"],
            "contactor_batt":       parsed["contactor_batt"],
            "load_contactor":       parsed["load_contactor"],
        })

    def error_received(self, exc: Exception) -> None:
        logging.getLogger(__name__).error("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        logging.getLogger(__name__).warning("UDP connection lost: %s", exc)


async def main() -> None:
    cfg = load_config()

    log_level = getattr(logging, cfg["log_level"].upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Batrium UDP addon starting — system_name=%s", cfg["system_name"])

    sys_id = 0   # placeholder; unique_ids are stable via system_name + sys_id combo

    # Delete old 'node_N' entities (replaced by 'cell_N') — empty retained payload removes from HA
    delete_configs = []
    for n in range(1, 17):
        delete_configs.extend(build_node_delete_configs(n, sys_id))

    pack_discovery = build_discovery_configs(cfg["system_name"], sys_id)

    publisher = BatriumPublisher(
        host=cfg["mqtt_host"],
        port=cfg["mqtt_port"],
        username=cfg["mqtt_username"],
        password=cfg["mqtt_password"],
        system_name=cfg["system_name"],
        discovery_configs=delete_configs + pack_discovery,  # deletions published first
    )
    publisher.start()

    loop = asyncio.get_event_loop()
    logger.info("Binding UDP on 0.0.0.0:%d", cfg["udp_port"])
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: BatriumUdpProtocol(publisher, cfg["system_name"], sys_id),
        local_addr=("0.0.0.0", cfg["udp_port"]),
        allow_broadcast=True,
    )

    logger.info("Listening for Batrium WatchMon broadcasts...")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down")
        transport.close()
        publisher.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
