"""
seed_graph.py

Standalone script (not part of the deployed Function) to build the switch
twin graph from scratch: uploads the DTDL model, creates all switch twins,
and wires up the connectedTo relationships between them.

Run with: python seed_graph.py
Requires ADT_ENDPOINT to be exported in your shell first (same as
your other isolation testing).
"""

import json
import os
from azure.core.exceptions import ResourceExistsError
import logging
from cascade_logic import get_adt_client


SWITCHES = {
    "DMZ-FW-SW01": {"zone": "DMZ", "ipAddress": "10.10.1.1", "isGateway": True},
    "DMZ-CORE-SW02": {"zone": "DMZ", "ipAddress": "10.10.1.2", "isGateway": False},
    "OT-HIST-SW03": {"zone": "OT", "ipAddress": "10.10.1.3", "isGateway": False},
    "OT-PLC-SW04": {"zone": "OT", "ipAddress": "10.10.1.4", "isGateway": False},
    "OT-PLC-SW05": {"zone": "OT", "ipAddress": "10.10.1.5", "isGateway": False},
    "OT-HMI-SW06": {"zone": "OT", "ipAddress": "10.10.1.6", "isGateway": False},
    "IT-EDGE-SW07": {"zone": "IT", "ipAddress": "10.10.1.7", "isGateway": False}
}

EDGES = [
    ("DMZ-FW-SW01", "DMZ-CORE-SW02"),
    ("DMZ-FW-SW01", "IT-EDGE-SW07"),
    ("DMZ-CORE-SW02", "OT-HIST-SW03"),
    ("DMZ-CORE-SW02", "OT-PLC-SW04"),
    ("DMZ-CORE-SW02", "OT-HMI-SW06"),
    ("OT-HMI-SW06", "OT-HIST-SW03"),
    ("OT-PLC-SW04", "OT-PLC-SW05")    
]


def upload_model(client) -> None:
    """Upload models/switch.json to the ADT instance (idempotent)."""
    model_path = os.path.join(os.path.dirname(__file__), "..", "models", "switch.json")
    with open(model_path) as f:
        model = json.load(f)
    try:
        client.create_models([model])
    except ResourceExistsError:
        logging.info("Model already exists, skipping upload.") 


def create_switch_twin(client, twin_id: str, properties: dict) -> None:
    """Upsert a single switch twin with status defaulted to online."""
    twin = {
        "$metadata": {"$model": "dtmi:com:refinery:Switch;1"},
        "status": "online",
        **properties,
    }
    client.upsert_digital_twin(twin_id, twin)


def create_link(client, twin_id: str, target_id: str) -> None:
    """Upsert one directed connectedTo relationship, linkStatus=up."""
    relationship_id = f"{twin_id}-to-{target_id}"
    relationship = {
        "$relationshipName": "connectedTo",
        "$targetId": target_id,
        "linkStatus": "up",
    }
    client.upsert_relationship(twin_id, relationship_id, relationship)


def seed_graph(client) -> None:
    """Build the whole graph: model, twins, then both directions of every edge."""
    upload_model(client)

    for twin_id, properties in SWITCHES.items():
        create_switch_twin(client, twin_id, properties)
        logging.info(f"Created twin: {twin_id}")

    for a, b in EDGES:
        create_link(client, a, b)
        create_link(client, b, a)
        logging.info(f"Linked {a} <-> {b}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = get_adt_client()
    seed_graph(client)
    print("Graph seed complete.")
