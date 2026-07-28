import logging
from azure.digitaltwins.core import DigitalTwinsClient

GATEWAY_ID = "DMZ-FW-SW01"


def get_up_neighbors(client: DigitalTwinsClient, twin_id: str) -> list[str]:
    """Target twin IDs of every outgoing connectedTo relationship that's currently 'up'."""
    neighbors = []
    for rel in client.list_relationships(twin_id):
        if rel.get("$relationshipName") == "connectedTo" and rel.get("linkStatus") == "up":
            neighbors.append(rel["$targetId"])
    return neighbors


def find_reachable_twins(client: DigitalTwinsClient, gateway_id: str) -> set[str]:
    """BFS from the gateway over 'up' edges. Returns reachable twin IDs, gateway included."""
    visited = {gateway_id}
    frontier = [gateway_id]
    while frontier:
        twin_id = frontier.pop(0)
        for neighbor in get_up_neighbors(client, twin_id):
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    return visited


def recompute_reachability(client: DigitalTwinsClient, gateway_id: str) -> list[tuple[str, str]]:
    """Recompute reachability from the gateway, patch any twin whose status
    changed, and return the transitions as (switch_id, "unreachable"|"recovered").
    Safe to call after any link event -- re-derives truth from current
    linkStatus rather than assuming what changed."""
    reachable = find_reachable_twins(client, gateway_id)

    all_twins = list(client.query_twins("SELECT * FROM digitaltwins"))

    transitions = []
    for twin in all_twins:
        twin_id = twin["$dtId"]
        old_status = twin.get("status")
        new_status = "online" if twin_id in reachable else "unreachable"

        if old_status == new_status:
            continue

        patch = [{"op": "replace", "path": "/status", "value": new_status}]
        client.update_digital_twin(twin_id, patch)

        if new_status == "unreachable":
            transitions.append((twin_id, "unreachable"))
            logging.info(f"Twin ID: {twin_id} is now unreachable from gateway {gateway_id}")
        else:
            transitions.append((twin_id, "recovered"))
            logging.info(f"Twin ID: {twin_id} has recovered, reachable from gateway {gateway_id}")

    return transitions
