import azure.functions as func
import datetime
import json
import logging
from cascade_logic import get_adt_client, cascade_failure

app = func.FunctionApp()


@app.event_hub_message_trigger(arg_name="azeventhub", event_hub_name="iot-refinery-blastradius",
                               connection="EventHubConnectionString") 
def CascadeProcessor(azeventhub: func.EventHubEvent):
    
    body = json.loads(azeventhub.get_body().decode('utf-8'))
    logging.info(f"Test message. Received: {body}")
    device_id = azeventhub.metadata.get("SystemProperties", {}).get("iothub-connection-device-id")
    if not device_id:
        logging.warning("Could not determine device ID from event metadata; skipping.")
        return
    if body.get("status") == "offline":
        client = get_adt_client()
        patch = [    
            {"op": "replace", "path": "/status", "value": body.get("status")}
        ] 
        client.update_digital_twin(device_id, patch)
        cascade_failure(client, device_id)
        logging.info(f"{device_id} triggered cascade failure.")
        
    # --- What about "online" events? ---
    # TODO (optional, worth thinking about even if you don't build it
    # this weekend): right now nothing handles recovery -- if the
    # compressor comes back online, downstream twins stay marked
    # unreachable forever. Would fixing this need a NEW function, or
    # could cascade_failure's shape be reused/inverted for a
    # "cascade_recovery"? You don't need to build this now, but it's
    # worth having an opinion on before you write your README's
    # "future work" section.


@app.route(route="GraphStatus", auth_level=func.AuthLevel.ANONYMOUS)
def GraphStatus(req: func.HttpRequest) -> func.HttpResponse:
    """
    Returns the current state of the entire twin graph as JSON, so a
    frontend dashboard can render it without needing its own ADT
    credentials.
    """

    client = get_adt_client()
    query = f"Select * FROM digitaltwins"
    twins = list(client.query_twins(query))

    relations = []
    for twin in twins:
        twin_id = twin['$dtId']
        for rel in client.list_relationships(twin_id):
            relations.append(rel)

    response_body = {"twins": twins, "relationships": relations}

    return func.HttpResponse(json.dumps(response_body), status_code=200, mimetype="application/json")
