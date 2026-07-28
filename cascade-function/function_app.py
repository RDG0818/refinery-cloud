import azure.functions as func
import json
import logging
from cascade_logic import get_adt_client
from reachability_logic import recompute_reachability, GATEWAY_ID
from table_client import insert_alert, fetch_recent_alerts
from email_client import send_alert_email

app = func.FunctionApp()


@app.event_hub_message_trigger(arg_name="azeventhub", event_hub_name="%EVENT_HUB_NAME%",
                               connection="EventHubConnectionString")
def LinkEventProcessor(azeventhub: func.EventHubEvent):
    body = json.loads(azeventhub.get_body().decode('utf-8'))
    logging.info(f"Link event received: {body}")

    source_id = body.get("sourceSwitch")
    target_id = body.get("targetSwitch")
    link_status = body.get("linkStatus")
    if not source_id or not target_id or link_status not in ("up", "down"):
        logging.warning(f"Malformed link event, skipping: {body}")
        return

    client = get_adt_client()

    # Each mesh link is two directed relationships (see seed_graph.py) --
    # both need the same linkStatus.
    for a, b in [(source_id, target_id), (target_id, source_id)]:
        relationship_id = f"{a}-to-{b}"
        patch = [{"op": "replace", "path": "/linkStatus", "value": link_status}]
        client.update_relationship(a, relationship_id, patch)

    transitions = recompute_reachability(client, GATEWAY_ID)

    for switch_id, event_type in transitions:
        insert_alert(switch_id, event_type)
        send_alert_email(switch_id, event_type)

    logging.info(
        f"Link {source_id} <-> {target_id} set to {link_status}; "
        f"{len(transitions)} switch(es) transitioned."
    )


@app.route(route="GraphStatus", auth_level=func.AuthLevel.ANONYMOUS)
def GraphStatus(req: func.HttpRequest) -> func.HttpResponse:
    """Returns the current twin graph as JSON so the dashboard can render it
    without needing its own ADT credentials."""
    client = get_adt_client()
    query = "SELECT * FROM digitaltwins"
    twins = list(client.query_twins(query))

    relations = []
    for twin in twins:
        twin_id = twin['$dtId']
        for rel in client.list_relationships(twin_id):
            relations.append(rel)

    response_body = {"twins": twins, "relationships": relations}

    return func.HttpResponse(json.dumps(response_body), status_code=200, mimetype="application/json")


@app.route(route="AlertHistory", auth_level=func.AuthLevel.ANONYMOUS)
def AlertHistory(req: func.HttpRequest) -> func.HttpResponse:
    """Returns the most recent switch alerts (unreachable/recovered events)
    from Table Storage, so the dashboard can show an alert feed."""
    limit = req.params.get("limit", 50)
    alerts = fetch_recent_alerts(limit)
    return func.HttpResponse(json.dumps(alerts), status_code=200, mimetype="application/json")
