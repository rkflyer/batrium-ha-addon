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

# CONNACK return codes (MQTT 3.1.1 / paho-mqtt 1.x). Reported as a bare number
# until 1.0.6, which is useless to anyone who does not already know the table —
# and rc=5 in particular has exactly one cause, so leaving it as "rc=5" turned a
# solvable config mistake into a bug report.
CONNACK_MEANING = {
    1: "the broker rejected the MQTT protocol version",
    2: "the broker rejected this client ID",
    3: "the broker is unavailable",
    4: "the broker rejected the username/password",
    5: "the broker refused the connection as not authorised",
}

# Appended for the two codes a user can actually act on.
CREDENTIAL_HINT = (
    " Check the addon's mqtt_username / mqtt_password. With the Mosquitto addon "
    "these must be a Home Assistant user that exists — leaving them blank, or "
    "using an account Mosquitto does not accept, produces exactly this error."
)


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
        # Distinct from _connected: has a connection EVER succeeded? A broker that
        # refuses us from the start looks the same as one we lost, but only the
        # first case means nothing has ever reached Home Assistant.
        self._ever_connected    = False
        self._timer: threading.Timer | None = None

    @property
    def ever_connected(self) -> bool:
        """True once a connection has succeeded at least once since startup."""
        return self._ever_connected

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

    def publish_node_discovery(self, configs: list[tuple[str, str]]) -> bool:
        """
        Publish discovery configs for a newly-seen node.

        Also appends them to the internal list so they are republished
        on every future reconnect (HA forgets retained topics on restart
        if we don't re-publish them).

        Returns True if the configs went out now, False if they were only
        queued because MQTT is not connected. The caller needs to know which:
        until 1.0.6 it logged "published" either way, so an addon that had never
        reached the broker still reported publishing entities for every node it
        found — which reads as working, and sent at least one user hunting the
        wrong fault entirely.

        Safe to call from any thread.
        """
        with self._discovery_lock:
            self._discovery_configs.extend(configs)
        if not self._connected:
            return False
        for topic, payload in configs:
            self._client.publish(topic, payload, retain=True)
            _LOGGER.debug("Node discovery published: %s", topic)
        return True

    # ------------------------------------------------------------------
    # MQTT callbacks

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            reason = CONNACK_MEANING.get(rc, "the broker refused the connection")
            hint = CREDENTIAL_HINT if rc in (4, 5) else ""
            _LOGGER.error(
                "MQTT connect to %s:%d failed — %s (rc=%d). Nothing can be "
                "published until this is fixed, so no entities will appear in "
                "Home Assistant.%s Retrying.",
                self._host, self._port, reason, rc, hint,
            )
            return
        _LOGGER.info("MQTT connected to %s:%d", self._host, self._port)
        self._connected = True
        self._ever_connected = True

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
        # paho fires on_disconnect after a REFUSED connect too, carrying the same
        # CONNACK code — so a broker rejecting us produced two log lines per retry
        # saying the same thing in different words. _on_connect has already
        # explained it properly; don't say it again in a less useful form.
        if not self._ever_connected:
            _LOGGER.debug("MQTT disconnect callback (rc=%d) after a refused connect", rc)
        else:
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
