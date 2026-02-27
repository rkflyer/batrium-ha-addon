"""
paho-mqtt wrapper with:
- Async connect (non-blocking loop_start)
- LWT (last will) for availability tracking
- Auto-discovery publish on connect / reconnect
- Dynamic node discovery: publish per-node entities as new nodes are seen
- Periodic state publish (1s timer, throttles 300ms UDP rate)
- Thread-safe state updates from asyncio datagram handler
"""

import json
import logging
import threading

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

PUBLISH_INTERVAL = 1.0  # seconds


class BatriumPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        system_name: str,
        discovery_configs: list[tuple[str, str]],
    ):
        self._host              = host
        self._port              = port
        self._system_name       = system_name
        self._state_topic       = f"batrium/{system_name}/state"
        self._avail_topic       = f"batrium/{system_name}/availability"

        # discovery_configs is appended to as new nodes are discovered at runtime;
        # the full list is republished on every reconnect so HA always has everything.
        self._discovery_configs = list(discovery_configs)
        self._discovery_lock    = threading.Lock()

        self._client = mqtt.Client(
            client_id=f"batrium_{system_name}",
            clean_session=True,
        )
        if username:
            self._client.username_pw_set(username, password or None)

        # LWT so HA marks entities unavailable if the addon crashes
        self._client.will_set(self._avail_topic, "offline", retain=True)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        self._state: dict       = {}
        self._state_lock        = threading.Lock()
        self._connected         = False
        self._timer: threading.Timer | None = None

    # ------------------------------------------------------------------
    # Public API

    def start(self) -> None:
        """Connect (non-blocking) and start the MQTT network loop."""
        _LOGGER.info("Connecting to MQTT broker at %s:%d", self._host, self._port)
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        """Publish offline status, stop loop, disconnect cleanly."""
        self._cancel_timer()
        try:
            self._client.publish(self._avail_topic, "offline", retain=True)
        except Exception:
            pass
        self._client.loop_stop()
        self._client.disconnect()

    def update_state(self, updates: dict) -> None:
        """Thread-safe merge of new values into the in-memory state dict."""
        with self._state_lock:
            self._state.update(updates)

    def publish_node_discovery(self, configs: list[tuple[str, str]]) -> None:
        """
        Publish discovery configs for a newly-seen node.

        Also appends them to the internal list so they are republished
        on every future reconnect (HA forgets retained topics on restart
        if we don't re-publish them).

        Safe to call from any thread.
        """
        with self._discovery_lock:
            self._discovery_configs.extend(configs)
        if self._connected:
            for topic, payload in configs:
                self._client.publish(topic, payload, retain=True)
                _LOGGER.debug("Node discovery published: %s", topic)

    # ------------------------------------------------------------------
    # MQTT callbacks

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            _LOGGER.error("MQTT connect failed (rc=%d) — will retry", rc)
            return
        _LOGGER.info("MQTT connected to %s:%d", self._host, self._port)
        self._connected = True

        # Publish all discovery configs (pack-level + any per-node already seen)
        with self._discovery_lock:
            configs = list(self._discovery_configs)
        for topic, payload in configs:
            client.publish(topic, payload, retain=True)
        _LOGGER.info("Published %d discovery configs", len(configs))

        # Mark entities as available
        client.publish(self._avail_topic, "online", retain=True)

        # Start periodic state publish
        self._schedule_publish()

    def _on_disconnect(self, client, userdata, rc):
        _LOGGER.warning("MQTT disconnected (rc=%d) — paho will reconnect", rc)
        self._connected = False
        self._cancel_timer()

    # ------------------------------------------------------------------
    # State publish loop

    def _schedule_publish(self) -> None:
        self._timer = threading.Timer(PUBLISH_INTERVAL, self._publish_state)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _publish_state(self) -> None:
        if not self._connected:
            return
        with self._state_lock:
            state = dict(self._state)
        if state:
            payload = json.dumps(state)
            self._client.publish(self._state_topic, payload)
            _LOGGER.debug("State published (%d bytes)", len(payload))
        self._schedule_publish()
