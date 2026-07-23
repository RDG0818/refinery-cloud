"""
reset_graph.py

Standalone script (not part of the deployed Function) to reset the switch
graph back to a healthy baseline: sets every connectedTo relationship's
linkStatus back to "up", then recomputes reachability from the gateway so
every twin's status flips back to "online".

Run with: python reset_graph.py
Requires ADT_ENDPOINT to be exported in your shell first (same as
your other isolation testing).
"""

import logging
from cascade_logic import get_adt_client
from reachability_logic import recompute_reachability, GATEWAY_ID


def reset_all_links(client) -> None:
    """Walk every twin's outgoing connectedTo relationships and set
    linkStatus back to 'up'."""
    all_twins = list(client.query_twins("SELECT * FROM digitaltwins"))

    for twin in all_twins:
        twin_id = twin["$dtId"]
        for rel in client.list_relationships(twin_id):
            if rel.get("$relationshipName") != "connectedTo":
                continue
            relationship_id = rel["$relationshipId"]
            patch = [{"op": "replace", "path": "/linkStatus", "value": "up"}]
            client.update_relationship(twin_id, relationship_id, patch)
            logging.info(f"Reset link {twin_id} -> {rel['$targetId']} to up")


def reset_graph(client) -> None:
    """Reset every link to up, then recompute reachability so every twin's
    status flips back to online."""
    reset_all_links(client)
    transitions = recompute_reachability(client, GATEWAY_ID)
    for twin_id, event_type in transitions:
        logging.info(f"{twin_id}: {event_type}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = get_adt_client()
    reset_graph(client)
    print("Graph reset complete.")
