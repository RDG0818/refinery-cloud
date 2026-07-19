import os
import logging
from azure.identity import DefaultAzureCredential
from azure.digitaltwins.core import DigitalTwinsClient


def get_adt_client() -> DigitalTwinsClient:
    """Build and return an authenticated client for talking to Azure Digital Twins."""
    ADT_HOSTNAME = os.getenv("ADT_ENDPOINT") # functions runtime adds local.settings.json to env vars
    if not ADT_HOSTNAME:
        raise RuntimeError("ADT_ENDPOINT environment variable is not set")
    creds = DefaultAzureCredential()
    return DigitalTwinsClient(ADT_HOSTNAME, creds)


def find_downstream_twins(client: DigitalTwinsClient, source_twin_id: str) -> list[str]:
    """Given a twin ID, find every twin it directly points to via the
    'feedsNetworkTo' relationship (i.e. one hop downstream)."""
    adt_query_string = (
        f"SELECT Target.$dtId FROM digitaltwins Source "
        f"JOIN Target RELATED Source.feedsNetworkTo "
        f"WHERE Source.$dtId = '{source_twin_id}'"
    )
    results = client.query_twins(adt_query_string)
    id_fields = [row["$dtId"] for row in results] 
    return id_fields


def mark_twin_unreachable(client: DigitalTwinsClient, twin_id: str) -> None:
    """Patch a single twin to reflect that it's been cut off by an upstream failure."""
    patch = [    
        {"op": "replace", "path": "/isConnected", "value": False},
        {"op": "replace", "path": "/status", "value": "unreachable"}
      ] 
    client.update_digital_twin(twin_id, patch)
    logging.info(f"Twin ID: {twin_id} has been marked as unreachable")


def cascade_failure(client: DigitalTwinsClient, source_twin_id: str) -> None:
    """
    The actual blast-radius algorithm. Starting from the twin that just
    went offline, walk the graph outward and mark every twin found
    along the way as unreachable -- no matter how many hops deep.
    """
    frontier = [source_twin_id]
    while not len(frontier) == 0:
      twin_id = frontier.pop(0)
      downstream_twins = find_downstream_twins(client, twin_id)
      for twin in downstream_twins:
          mark_twin_unreachable(client, twin)
          frontier.append(twin)
