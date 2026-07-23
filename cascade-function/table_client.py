import os
import uuid
from datetime import datetime, timezone
from azure.data.tables import TableClient

TABLE_NAME = "SwitchAlerts"


def get_table_client() -> TableClient:
    """Open a client for the SwitchAlerts table. Expects
    TABLES_CONNECTION_STRING in the environment (same storage account
    the Function App already uses for AzureWebJobsStorage)."""
    connection_string = os.environ["TABLES_CONNECTION_STRING"]
    return TableClient.from_connection_string(connection_string, table_name=TABLE_NAME)


def insert_alert(switch_id: str, event_type: str, detail: str | None = None) -> None:
    """Insert one row into SwitchAlerts. event_type should be
    'unreachable' or 'recovered'."""
    entity = {
        "PartitionKey": "alert",
        "RowKey": str(uuid.uuid4()),
        "switch_id": switch_id,
        "event_type": event_type,
        "detected_at": datetime.now(timezone.utc),
    }
    if detail is not None:
        entity["detail"] = detail

    client = get_table_client()
    client.create_entity(entity)


def fetch_recent_alerts(limit: int = 50) -> list[dict]:
    """Return the most recent alerts, newest first. Table Storage has no
    server-side ORDER BY, so this pulls the (small) alert log and sorts
    in Python -- simplest option for low alert volume."""
    limit = int(limit)
    client = get_table_client()
    entities = list(client.list_entities())
    entities.sort(key=lambda e: e["detected_at"], reverse=True)

    alerts = []
    for e in entities[:limit]:
        alerts.append({
            "switch_id": e["switch_id"],
            "event_type": e["event_type"],
            "detected_at": e["detected_at"].isoformat(),
            "detail": e.get("detail"),
        })
    return alerts
