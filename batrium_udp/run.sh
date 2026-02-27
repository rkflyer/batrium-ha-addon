#!/usr/bin/with-contenv bashio

export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USERNAME=$(bashio::config 'mqtt_username')
export MQTT_PASSWORD=$(bashio::config 'mqtt_password')
export UDP_PORT=$(bashio::config 'udp_port')
export SYSTEM_NAME=$(bashio::config 'system_name')
export LOG_LEVEL=$(bashio::config 'log_level')

bashio::log.info "Starting Batrium UDP addon (system: ${SYSTEM_NAME})"

python3 /app/batrium/main.py
