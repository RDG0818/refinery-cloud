import logging
from azure.digitaltwins.core import DigitalTwinsClient

GATEWAY_ID = "DMZ-FW-SW01"


def get_up_neighbors(client: DigitalTwinsClient, twin_id: str) -> list[str]:
    """Return the target twin IDs of every outgoing connectedTo relationship
    from this twin whose linkStatus is currently 'up'."""
    neighbors = []
    for rel in client.list_relationships(twin_id):
        if rel.get("$relationshipName") == "connectedTo" and rel.get("linkStatus") == "up":
            neighbors.append(rel["$targetId"])
    return neighbors


def find_reachable_twins(client: DigitalTwinsClient, gateway_id: str) -> set[str]:
    """BFS outward from the gateway twin over 'up' connectedTo edges only.
    Returns the set of twin IDs reachable from the gateway (gateway included)."""
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
    """
    Recompute reachability for the whole switch graph from the gateway twin,
    patch any twin whose status changed, and return the list of transitions
    as (switch_id, "unreachable" | "recovered") so the caller can alert on them.

    Safe to call after ANY link event (up or down) -- it doesn't assume which
    direction changed, it just re-derives the truth from current linkStatus
    values and diffs against what's currently stored.
    """
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
