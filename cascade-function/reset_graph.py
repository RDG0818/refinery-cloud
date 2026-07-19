"""
reset_graph.py

Standalone script (not part of the deployed Function) to reset every
twin in the refinery graph back to a healthy baseline state. Useful
for re-running tests without leftover state from a previous cascade.

Run with: python reset_graph.py
Requires ADT_ENDPOINT to be exported in your shell first (same as
your other isolation testing).
"""

import logging
from cascade_logic import get_adt_client, find_downstream_twins


def reset_twin_to_healthy(client, twin_id: str, is_source: bool = False) -> None:
    """Patch a single twin back to a healthy state."""
    if is_source: 
        patch = [    
          {"op": "replace", "path": "/status", "value": "online"}
        ] 
    else:
        patch = [    
          {"op": "replace", "path": "/isConnected", "value": True},
          {"op": "replace", "path": "/status", "value": "online"}
        ]

    client.update_digital_twin(twin_id, patch)



def reset_graph(client, source_twin_id: str) -> None:
    """
    Walk the graph from the source twin and reset every twin found
    -- source and all downstream descendants -- back to healthy.
    """

    reset_twin_to_healthy(client, source_twin_id, is_source=True)
    frontier = [source_twin_id]
    while not len(frontier) == 0:
      twin_id = frontier.pop(0)
      downstream_twins = find_downstream_twins(client, twin_id)
      for twin in downstream_twins:
          reset_twin_to_healthy(client, twin)
          logging.info(f"Reset {twin} to online.")
          frontier.append(twin)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = get_adt_client()
    reset_graph(client, "Compressor-01")
    print("Graph reset complete.")
    