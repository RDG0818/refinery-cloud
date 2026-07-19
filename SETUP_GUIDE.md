# Refinery Blast Radius — Setup Guide

A cascading-failure simulator built on Azure Digital Twins. A `Compressor-01`
twin feeds two `Pump` twins, each of which feeds two `Sensor` twins. When the
compressor goes offline, an Azure Function walks the graph and marks every
downstream twin `unreachable`.

This guide captures the full setup in the correct order, with the exact
resource names used in this project. Swap names/regions if you're
reproducing this from scratch and hit a naming or region conflict.

---

## 0. Prerequisites

- Arch Linux (or any distro — adjust the install step accordingly)
- An Azure subscription (Azure for Students works fine, free-tier throughout)

---

## 1. Install and configure Azure CLI

```bash
sudo pacman -Syu azure-cli
az version
```

Log in — device-code flow is more reliable than browser handoff on
Wayland/tiling WM setups:

```bash
az login --use-device-code
```

Confirm the right subscription is active:

```bash
az account show
az account set --subscription "<name-or-id>"   # only if needed
```

Add the IoT extension (this also covers `az dt` Digital Twins commands):

```bash
az extension add --name azure-iot
```

---

## 2. Resource group

```bash
az group create --name rg-refinery-blastradius --location westcentralus
```

> Note: the resource group's location is just metadata — resources inside it
> can live in a different region. In this project, ADT/IoT Hub/Storage/
> Function App all ended up in `eastus` due to a subscription location
> policy that disallowed `westcentralus` for some resource types. Check
> your own allowed regions before assuming a region works:
> ```bash
> az provider show --namespace Microsoft.DigitalTwins \
>   --query "resourceTypes[?resourceType=='digitalTwinsInstances'].locations" -o tsv
> az provider show --namespace Microsoft.Devices \
>   --query "resourceTypes[?resourceType=='IotHubs'].locations" -o tsv
> ```

---

## 3. Register resource providers up front

Save yourself the trial-and-error — register everything needed before
creating resources:

```bash
az provider register --namespace Microsoft.DigitalTwins
az provider register --namespace Microsoft.Devices
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.Web
az provider register --namespace Microsoft.Insights
az provider register --namespace Microsoft.OperationalInsights
```

Check status of any of them with:

```bash
az provider show --namespace <namespace> --query registrationState -o tsv
```

---

## 4. Azure Digital Twins instance

```bash
az dt create -n adt-refinery-blastradius -g rg-refinery-blastradius -l eastus
```

Grant yourself data-plane access (control-plane ownership from creating the
resource does NOT include this — it's a separate permission):

```bash
az dt role-assignment create \
  --dt-name adt-refinery-blastradius \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Azure Digital Twins Data Owner"
```

Get the instance hostname (needed for `ADT_ENDPOINT` and ADT Explorer):

```bash
az dt show -n adt-refinery-blastradius -g rg-refinery-blastradius --query "hostName" -o tsv
```

**ADT Explorer** (visual graph browser): go to
`https://explorer.digitaltwins.azure.net/`, sign in, and paste
`https://<hostname-from-above>` into the Digital Twin URL field.

---

## 5. IoT Hub

```bash
az iot hub create \
  --name iot-refinery-blastradius \
  --resource-group rg-refinery-blastradius \
  --location eastus \
  --sku F1 \
  --partition-count 2
```

> F1 is the free tier — one per subscription. If you've created an F1 hub
> before on this subscription, this will fail; use `S1` instead (fractions
> of a cent at this message volume).

Register the device that will pretend to be the compressor:

```bash
az iot hub device-identity create \
  --hub-name iot-refinery-blastradius \
  --device-id Compressor-01
```

Get its connection string (used by the local simulator to send telemetry —
treat as a secret, never commit it):

```bash
az iot hub device-identity connection-string show \
  --hub-name iot-refinery-blastradius \
  --device-id Compressor-01 \
  -o tsv
```

Get the **service-side** Event Hub-compatible connection string (used by the
Function to *read* the stream — different from the device connection
string above):

```bash
az iot hub connection-string show \
  --hub-name iot-refinery-blastradius \
  --default-eventhub \
  --output tsv
```

---

## 6. DTDL models

```bash
mkdir -p ~/projects/refinery-blast-radius/models
cd ~/projects/refinery-blast-radius
```

`models/compressor.json`:

```json
{
  "@id": "dtmi:com:refinery:Compressor;1",
  "@type": "Interface",
  "@context": "dtmi:dtdl:context;2",
  "displayName": "Refinery Compressor",
  "contents": [
    { "@type": "Property", "name": "status", "schema": "string" },
    {
      "@type": "Relationship",
      "name": "feedsNetworkTo",
      "target": "dtmi:com:refinery:Pump;1",
      "displayName": "Feeds Pressure To"
    }
  ]
}
```

`models/pump.json`:

```json
{
  "@id": "dtmi:com:refinery:Pump;1",
  "@type": "Interface",
  "@context": "dtmi:dtdl:context;2",
  "displayName": "Refinery Pump",
  "contents": [
    { "@type": "Property", "name": "status", "schema": "string" },
    { "@type": "Property", "name": "isConnected", "schema": "boolean" },
    {
      "@type": "Relationship",
      "name": "feedsNetworkTo",
      "target": "dtmi:com:refinery:Sensor;1",
      "displayName": "Feeds Data To"
    }
  ]
}
```

`models/sensor.json`:

```json
{
  "@id": "dtmi:com:refinery:Sensor;1",
  "@type": "Interface",
  "@context": "dtmi:dtdl:context;2",
  "displayName": "Refinery Sensor",
  "contents": [
    { "@type": "Property", "name": "status", "schema": "string" },
    { "@type": "Property", "name": "isConnected", "schema": "boolean" },
    { "@type": "Property", "name": "readingType", "schema": "string" }
  ]
}
```

Upload all three at once:

```bash
az dt model create --dt-name adt-refinery-blastradius --from-directory models
```

---

## 7. Build the twin graph

```bash
# Compressor
az dt twin create --dt-name adt-refinery-blastradius \
  --dtmi "dtmi:com:refinery:Compressor;1" \
  --twin-id Compressor-01 \
  --properties '{"status": "online"}'

# Pumps
az dt twin create --dt-name adt-refinery-blastradius \
  --dtmi "dtmi:com:refinery:Pump;1" \
  --twin-id Pump-01 \
  --properties '{"status": "online", "isConnected": true}'

az dt twin create --dt-name adt-refinery-blastradius \
  --dtmi "dtmi:com:refinery:Pump;1" \
  --twin-id Pump-02 \
  --properties '{"status": "online", "isConnected": true}'

# Sensors
az dt twin create --dt-name adt-refinery-blastradius \
  --dtmi "dtmi:com:refinery:Sensor;1" \
  --twin-id Sensor-01 \
  --properties '{"status": "online", "isConnected": true, "readingType": "pressure"}'

az dt twin create --dt-name adt-refinery-blastradius \
  --dtmi "dtmi:com:refinery:Sensor;1" \
  --twin-id Sensor-02 \
  --properties '{"status": "online", "isConnected": true, "readingType": "flow"}'

az dt twin create --dt-name adt-refinery-blastradius \
  --dtmi "dtmi:com:refinery:Sensor;1" \
  --twin-id Sensor-03 \
  --properties '{"status": "online", "isConnected": true, "readingType": "pressure"}'

az dt twin create --dt-name adt-refinery-blastradius \
  --dtmi "dtmi:com:refinery:Sensor;1" \
  --twin-id Sensor-04 \
  --properties '{"status": "online", "isConnected": true, "readingType": "temperature"}'
```

Relationships (the graph edges the cascade logic walks):

```bash
az dt twin relationship create --dt-name adt-refinery-blastradius \
  --relationship-id "compressor-to-pump01" --relationship feedsNetworkTo \
  --twin-id Compressor-01 --target Pump-01

az dt twin relationship create --dt-name adt-refinery-blastradius \
  --relationship-id "compressor-to-pump02" --relationship feedsNetworkTo \
  --twin-id Compressor-01 --target Pump-02

az dt twin relationship create --dt-name adt-refinery-blastradius \
  --relationship-id "pump01-to-sensor01" --relationship feedsNetworkTo \
  --twin-id Pump-01 --target Sensor-01

az dt twin relationship create --dt-name adt-refinery-blastradius \
  --relationship-id "pump01-to-sensor02" --relationship feedsNetworkTo \
  --twin-id Pump-01 --target Sensor-02

az dt twin relationship create --dt-name adt-refinery-blastradius \
  --relationship-id "pump02-to-sensor03" --relationship feedsNetworkTo \
  --twin-id Pump-02 --target Sensor-03

az dt twin relationship create --dt-name adt-refinery-blastradius \
  --relationship-id "pump02-to-sensor04" --relationship feedsNetworkTo \
  --twin-id Pump-02 --target Sensor-04
```

Verify the whole graph:

```bash
az dt twin query --dt-name adt-refinery-blastradius \
  --query-command "SELECT * FROM digitaltwins"
```

Verify one hop of relationships:

```bash
az dt twin query --dt-name adt-refinery-blastradius \
  --query-command "SELECT Target.\$dtId FROM digitaltwins Source JOIN Target RELATED Source.feedsNetworkTo WHERE Source.\$dtId = 'Compressor-01'"
```

Verify two hops:

```bash
az dt twin query --dt-name adt-refinery-blastradius \
  --query-command "SELECT Compressor.\$dtId, Pump.\$dtId, Sensor.\$dtId FROM digitaltwins Compressor JOIN Pump RELATED Compressor.feedsNetworkTo JOIN Sensor RELATED Pump.feedsNetworkTo"
```

---

## 8. Storage account + Function App shell

```bash
az storage account create \
  --name strefinerybr \
  --resource-group rg-refinery-blastradius \
  --location eastus \
  --sku Standard_LRS

az functionapp create \
  --name func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --storage-account strefinerybr \
  --consumption-plan-location eastus \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type linux
```

---

## 9. Local Functions tooling

Install Core Tools (AUR, or npm as a fallback):

```bash
yay -S azure-functions-core-tools-bin
# or:
npm install -g azure-functions-core-tools@4 --unsafe-perm true

func --version
```

Scaffold the project:

```bash
cd ~/projects/refinery-blast-radius
func init cascade-function --python
cd cascade-function
```

Add the Event Hub-triggered function — note the exact template string,
which differs from what's shown in `func templates list`:

```bash
func new --name CascadeProcessor --template "EventHub trigger"
```

- **Event Hub name** prompt → enter `iot-refinery-blastradius` (IoT Hub's
  name — its built-in telemetry stream acts as the Event Hub endpoint).
- **Connection string setting name** prompt → accept the default; the
  scaffolded code will reference `EventHubConnectionString`.

---

## 10. Local settings

`cascade-function/local.settings.json`:

```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage": "<connection string from `az storage account show-connection-string --name strefinerybr --resource-group rg-refinery-blastradius -o tsv`>",
    "EventHubConnectionString": "<connection string from the `az iot hub connection-string show --default-eventhub` command in step 5>",
    "ADT_ENDPOINT": "https://<hostname from `az dt show` in step 4>"
  }
}
```

`AzureWebJobsStorage` must point at a real storage account (or a running
Azurite emulator) — Event Hub triggers need it for checkpoint bookkeeping.
This file is excluded from git by the `.gitignore` `func init` generates —
confirm that before ever running `git add .` in this folder.

Install Python dependencies:

`requirements.txt` (add to what `func init` scaffolds):

```
azure-functions
azure-digitaltwins-core
azure-identity
```

```bash
pip install -r requirements.txt --break-system-packages
```

---

## 11. Application code

`cascade_logic.py`:

```python
import os
import logging
from azure.identity import DefaultAzureCredential
from azure.digitaltwins.core import DigitalTwinsClient


def get_adt_client() -> DigitalTwinsClient:
    """Build and return an authenticated client for talking to Azure Digital Twins."""
    ADT_HOSTNAME = os.getenv("ADT_ENDPOINT")  # functions runtime adds local.settings.json to env vars
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
    """Breadth-first walk of the graph, marking every downstream twin
    unreachable, no matter how many hops deep."""
    frontier = [source_twin_id]
    while not len(frontier) == 0:
        twin_id = frontier.pop(0)
        downstream_twins = find_downstream_twins(client, twin_id)
        for twin in downstream_twins:
            mark_twin_unreachable(client, twin)
            frontier.append(twin)
```

`function_app.py`:

```python
import json
import logging
import azure.functions as func

from cascade_logic import get_adt_client, cascade_failure

app = func.FunctionApp()


@app.event_hub_message_trigger(arg_name="azeventhub", event_hub_name="iot-refinery-blastradius",
                               connection="EventHubConnectionString")
def CascadeProcessor(azeventhub: func.EventHubEvent):
    body = json.loads(azeventhub.get_body().decode('utf-8'))
    logging.info(f"Received: {body}")

    device_id = azeventhub.metadata.get("SystemProperties", {}).get("iothub-connection-device-id")
    if not device_id:
        logging.warning("Could not determine device ID from event metadata; skipping.")
        return

    if body.get("status") == "offline":
        client = get_adt_client()
        patch = [{"op": "replace", "path": "/status", "value": body.get("status")}]
        client.update_digital_twin(device_id, patch)
        cascade_failure(client, device_id)
        logging.info(f"{device_id} triggered cascade failure.")
```

`reset_graph.py` (standalone script, not deployed — restores the graph to
a healthy baseline between test runs):

```python
import logging
from cascade_logic import get_adt_client, find_downstream_twins


def reset_twin_to_healthy(client, twin_id: str, is_source: bool = False) -> None:
    if is_source:
        patch = [{"op": "replace", "path": "/status", "value": "online"}]
    else:
        patch = [
            {"op": "replace", "path": "/isConnected", "value": True},
            {"op": "replace", "path": "/status", "value": "online"}
        ]
    client.update_digital_twin(twin_id, patch)


def reset_graph(client, source_twin_id: str) -> None:
    reset_twin_to_healthy(client, source_twin_id, is_source=True)
    logging.info(f"Reset {source_twin_id} to online.")

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
```

---

## 12. Testing locally

Terminal 1 — start the Function host (reads `local.settings.json`, connects
to the real Azure IoT Hub and ADT instance):

```bash
cd ~/projects/refinery-blast-radius/cascade-function
func start
```

Terminal 2 — trigger a failure:

```bash
az iot device send-d2c-message \
  --hub-name iot-refinery-blastradius \
  --device-id Compressor-01 \
  --data '{"status": "offline"}'
```

Check the graph reflects the cascade:

```bash
az dt twin query --dt-name adt-refinery-blastradius \
  --query-command "SELECT * FROM digitaltwins WHERE status != 'online'"
```

Should return all 7 twins (compressor `offline`, 2 pumps + 4 sensors
`unreachable`).

Reset back to a clean baseline for the next test:

```bash
export ADT_ENDPOINT="https://<hostname from step 4>"
python reset_graph.py
```

Confirm it's clean:

```bash
az dt twin query --dt-name adt-refinery-blastradius \
  --query-command "SELECT * FROM digitaltwins WHERE status != 'online'"
```

Should return empty.

---

## 13. Deploy the Function to Azure

Local testing rides on your own `az login` credentials. The deployed app
needs its own identity and its own copies of the app settings, since
`local.settings.json` is never uploaded.

Give the Function App a Managed Identity:

```bash
az functionapp identity assign \
  --name func-refinery-cascade \
  --resource-group rg-refinery-blastradius
```

Note the `principalId` from the output, then grant that identity the same
data-plane role you gave yourself back in step 4:

```bash
az dt role-assignment create \
  --dt-name adt-refinery-blastradius \
  --assignee "<principalId from above>" \
  --role "Azure Digital Twins Data Owner"
```

This is what lets `DefaultAzureCredential()` work unchanged in the deployed
app — once an identity exists, the credential chain picks it up
automatically instead of falling through to your CLI session.

Set the app settings on the deployed app (mirrors `local.settings.json`;
`AzureWebJobsStorage` is already set automatically at Function App
creation):

```bash
az functionapp config appsettings set \
  --name func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --settings \
    "EventHubConnectionString=<value from local.settings.json>" \
    "ADT_ENDPOINT=<value from local.settings.json>"
```

`az functionapp config appsettings set` deliberately prints `null` for the
values it just set — that's output redaction, not a failure. Confirm the
real values landed with:

```bash
az functionapp config appsettings list \
  --name func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --query "[?name=='EventHubConnectionString' || name=='ADT_ENDPOINT']"
```

Deploy the code (remote build — installs `requirements.txt` server-side,
can take a couple of minutes):

```bash
cd ~/projects/refinery-blast-radius/cascade-function
func azure functionapp publish func-refinery-cascade
```

Should finish with:

```
Functions in func-refinery-cascade:
    CascadeProcessor - [eventHubTrigger]
```

## 14. Confirm the deployed Function works end to end

No local terminal is involved this time — the deployed app processes the
event entirely in Azure.

```bash
export ADT_ENDPOINT="https://<your ADT hostname>"
python reset_graph.py

az iot device send-d2c-message \
  --hub-name iot-refinery-blastradius \
  --device-id Compressor-01 \
  --data '{"status": "offline"}'

az dt twin query --dt-name adt-refinery-blastradius \
  --query-command "SELECT * FROM digitaltwins WHERE status != 'online'"
```

All 7 twins non-online confirms the cloud deployment works independent of
your machine.

> Note: `func azure functionapp logstream` does not work on Linux
> Consumption/Flex plans — use the graph query above to confirm behavior,
> or Application Insights Live Metrics in the portal if you want to watch
> it happen in real time.

---

## 15. Read-side HTTP Function (for the dashboard)

Add a second function to the same project:

```bash
cd ~/projects/refinery-blast-radius/cascade-function
func new --name GraphStatus --template "HTTP trigger" --authlevel "anonymous"
```

`--authlevel anonymous` means no function key required — fine for a demo
returning non-sensitive status data; a production version would lock this
down. Add it to `function_app.py`:

```python
@app.route(route="GraphStatus", auth_level=func.AuthLevel.ANONYMOUS)
def GraphStatus(req: func.HttpRequest) -> func.HttpResponse:
    """Returns the current state of the entire twin graph as JSON."""
    client = get_adt_client()

    twins = list(client.query_twins("SELECT * FROM digitaltwins"))
    relationships = [
        rel for twin in twins for rel in client.list_relationships(twin['$dtId'])
    ]

    response_body = {"twins": twins, "relationships": relationships}

    return func.HttpResponse(
        json.dumps(response_body),
        status_code=200,
        mimetype="application/json"
    )
```

Notes on the shapes involved, since they weren't obvious up front:
- `client.query_twins(...)` and `client.list_relationships(...)` both
  return **lazy iterators**, not lists — wrap in `list(...)` to actually
  materialize them, and don't `append` an iterator itself onto a list
  (append what's *inside* it, e.g. via a loop or comprehension).
- `list_relationships(twin_id)` is scoped to **one twin at a time** — to
  get every relationship in the graph, loop over every twin ID and
  collect the results. Inefficient at real scale (thousands of twins),
  fine here.
- Each twin/relationship object prints like a dict and serializes fine
  with `json.dumps` directly in this SDK version — but worth confirming
  yourself with a quick `json.dumps(...)` test before trusting it, since
  some SDK versions return a dict-like wrapper needing an explicit
  `dict(...)` conversion.
- `func.HttpResponse(...)` requires the body to be `str`/`bytes`/
  `bytearray` — passing a raw dict throws `TypeError: response is
  expected to be either of str, bytes, or bytearray, got dict`. Always
  `json.dumps()` it first.

Test locally:

```bash
func start
curl http://localhost:7071/api/GraphStatus | python3 -m json.tool
```

Redeploy so the live app picks up both functions:

```bash
func azure functionapp publish func-refinery-cascade
```

Should list both:

```
Functions in func-refinery-cascade:
    CascadeProcessor - [eventHubTrigger]
    GraphStatus - [httpTrigger]
```

## 16. CORS

A browser-based frontend on a different origin needs the Function App to
explicitly allow it:

```bash
az functionapp cors add \
  --name func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --allowed-origins "http://localhost:5173"
```

(Add the deployed dashboard's real domain here too, once it exists.)

## 17. Debugging a deployed Function (when curl returns an error)

`func azure functionapp logstream` and `az webapp log tail` **do not work
on Linux Consumption/Flex plans** — both return 404s. Use Application
Insights directly instead:

```bash
az monitor app-insights query \
  --app func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --analytics-query "exceptions | order by timestamp desc | take 5"
```

or, if nothing shows there yet:

```bash
az monitor app-insights query \
  --app func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --analytics-query "traces | order by timestamp desc | take 20"
```

(Real example hit during this project: `ADT_ENDPOINT` had accidentally
been set to the Event Hub connection string instead of the ADT hostname —
surfaced as `ServiceRequestError: Failed to resolve 'endpoint=sb'` in the
exceptions log. Fixed by re-running `az functionapp config appsettings
set` with the correct value — no redeploy needed, app settings changes
take effect within about a minute.)

## 18. React dashboard

```bash
cd ~/projects/refinery-blast-radius
npm create vite@latest refinery-dashboard -- --template react
cd refinery-dashboard
npm install
npm install @xyflow/react
```

`@xyflow/react` (formerly `reactflow`) is the current package name for
this node/edge graph library.

Replace `src/App.jsx` entirely:

```jsx
import { useState, useEffect, useCallback } from 'react';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

const GRAPH_STATUS_URL = "https://func-refinery-cascade.azurewebsites.net/api/GraphStatus";
const POLL_INTERVAL_MS = 3000;

const NODE_POSITIONS = {
  "Compressor-01": { x: 300, y: 0 },
  "Pump-01": { x: 100, y: 150 },
  "Pump-02": { x: 500, y: 150 },
  "Sensor-01": { x: 0, y: 300 },
  "Sensor-02": { x: 200, y: 300 },
  "Sensor-03": { x: 400, y: 300 },
  "Sensor-04": { x: 600, y: 300 },
};

function colorForStatus(status) {
  if (status === "online") {
    return "green";
  } else if (status === "offline") {
    return "red";
  } else if (status === "unreachable") {
    return "orange";
  }
  return "gray"; // fallback for anything unexpected
}

function transformGraphData(apiData) {
  const nodes = apiData.twins.map((twin) => ({
    id: twin.$dtId,
    position: NODE_POSITIONS[twin.$dtId] || { x: 0, y: 0 },
    data: { label: `${twin.$dtId}\n${twin.status}` },
    style: {
      backgroundColor: colorForStatus(twin.status),
      color: "white",
      padding: 10,
      borderRadius: 6,
      whiteSpace: "pre-line",
      textAlign: "center",
    },
  }));

  const edges = apiData.relationships.map((rel) => ({
    id: rel.$relationshipId,
    source: rel.$sourceId,
    target: rel.$targetId,
  }));

  return { nodes, edges };
}

function App() {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [error, setError] = useState(null);

  const fetchGraphData = useCallback(async () => {
    try {
      const response = await fetch(GRAPH_STATUS_URL);
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      const apiData = await response.json();
      const { nodes: newNodes, edges: newEdges } = transformGraphData(apiData);
      setNodes(newNodes);
      setEdges(newEdges);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchGraphData();
    const intervalId = setInterval(fetchGraphData, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchGraphData]);

  return (
    <div style={{ width: "100vw", height: "100vh" }}>
      {error && (
        <div style={{ color: "red", padding: 10 }}>
          Error fetching graph: {error}
        </div>
      )}
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}

export default App;
```

Run it:

```bash
npm run dev
```

Open `http://localhost:5173` — should show the live graph, polling every
3 seconds, colored by status.

> Debugging note: hit an "Invalid hook call... more than one copy of
> React" error on first run, from `@xyflow/react`. `npm ls react` showed
> only one deduped copy, so it wasn't the usual duplicate-React cause —
> turned out to be Vite installed in the wrong directory. Worth checking
> `npm ls react` first regardless, since a genuine duplicate copy is the
> far more common cause of this error.

Confirmed working: switching `Compressor-01` between `online`/`offline`
via `send-d2c-message` correctly re-colors the whole graph live.

---

## Cost notes

- **IoT Hub F1, Function App Consumption plan**: permanently free within
  their grants (8,000 msgs/day; 1M executions + 400,000 GB-s per month).
  This project uses a negligible fraction of either.
- **Storage account**: no free tier, but fractions of a cent/month at this
  data volume.
- **Azure Digital Twins**: **no free tier** — pure consumption pricing
  across Operations (~$2.50/million), Messages (~$1/million), and Query
  Units (~$0.50/million). Manual/occasional testing is pennies total. The
  thing to actually avoid is leaving a dashboard **polling ADT
  continuously and unattended** for days — stop it when not actively
  demoing rather than leaving it open indefinitely.
- Azure for Students has no card on file — the subscription disables at
  credit exhaustion rather than silently charging. A budget alert is still
  worth setting as an early warning:

```bash
az consumption budget create \
  --budget-name refinery-project-budget \
  --amount 5 \
  --time-grain Monthly \
  --category Cost \
  --start-date "$(date +%Y-%m-01)" \
  --end-date "2027-01-01" \
  --resource-group rg-refinery-blastradius
```

---

## Not yet built

- Deploying the dashboard itself (currently local-only via `npm run dev`;
  Azure Static Web Apps free tier is the target — will need its deployed
  URL added to the Function App's CORS allowed origins)
- Recovery cascade (mirrors `cascade_failure`, not yet wired to any trigger)
- Infrastructure-as-code (Bicep/CLI script) for one-shot reproducibility
