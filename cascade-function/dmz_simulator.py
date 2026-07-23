"""
dmz_simulator.py

Standalone script (not part of the deployed Function, not in
requirements.txt -- only needs azure-iot-device installed locally) that
sends simulated link up/down telemetry for the refinery DMZ switch mesh
to IoT Hub. Replaces the manual `az iot device send-d2c-message` calls
from SETUP_GUIDE.md with something that runs continuously for a demo.

Only one IoT Hub device is used ("dmz-simulator") -- LinkEventProcessor
reads sourceSwitch/targetSwitch straight out of the message body, not
from IoT Hub device identity, so there's no need to register one device
per switch.

Run with: python dmz_simulator.py
Requires IOT_DEVICE_CONNECTION_STRING to be exported in your shell
(the connection string for the "dmz-simulator" IoT Hub device).
"""

import os
import json
import random
import time
import logging
from azure.iot.device import IoTHubDeviceClient, Message
from seed_graph import EDGES

# Cisco-style syslog lines -- purely cosmetic flavor, logged alongside the
# actual JSON payload that gets sent to IoT Hub.
SYSLOG_DOWN = "%LINK-3-UPDOWN: Interface GigabitEthernet0/{port}, changed state to down"
SYSLOG_UP = "%LINK-3-UPDOWN: Interface GigabitEthernet0/{port}, changed state to up"

HEARTBEAT_INTERVAL_SEC = 10
FLAP_CHANCE = 0.15  # probability of starting a new link-down event on each tick
FLAP_RECOVERY_DELAY_RANGE_SEC = (15, 45)  # how long a down link stays down


def build_link_event(source: str, target: str, link_status: str) -> dict:
    return {"sourceSwitch": source, "targetSwitch": target, "linkStatus": link_status}


def log_syslog(source: str, target: str, link_status: str) -> None:
    port = random.randint(1, 24)
    template = SYSLOG_DOWN if link_status == "down" else SYSLOG_UP
    logging.info(f"{source}: {template.format(port=port)} (peer: {target})")


def send_event(client: IoTHubDeviceClient, source: str, target: str, link_status: str) -> None:
    payload = build_link_event(source, target, link_status)
    client.send_message(Message(json.dumps(payload)))
    log_syslog(source, target, link_status)


def run_simulator(client: IoTHubDeviceClient) -> None:
    down_links = set()   # edges currently flapped down
    recovery_at = {}     # edge -> unix timestamp when it should come back up

    while True:
        now = time.time()

        # Recover any links whose timer has elapsed.
        for edge in list(down_links):
            if now >= recovery_at[edge]:
                source, target = edge
                send_event(client, source, target, "up")
                down_links.discard(edge)
                del recovery_at[edge]

        # Maybe flap a new link down.
        if random.random() < FLAP_CHANCE:
            edge = random.choice(EDGES)
            if edge not in down_links:
                source, target = edge
                send_event(client, source, target, "down")
                down_links.add(edge)
                recovery_at[edge] = now + random.uniform(*FLAP_RECOVERY_DELAY_RANGE_SEC)

        time.sleep(HEARTBEAT_INTERVAL_SEC)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    connection_string = os.environ["IOT_DEVICE_CONNECTION_STRING"]
    client = IoTHubDeviceClient.create_from_connection_string(connection_string)
    client.connect()
    try:
        run_simulator(client)
    finally:
        client.shutdown()
