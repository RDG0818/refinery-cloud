# Refinery DMZ Switch Monitor — Setup Guide

A network monitoring simulator built on Azure Digital Twins. 7 switches
(`DMZ-FW-SW01` the gateway, plus DMZ/OT/IT switches) form a flat mesh with
one redundant loop and one single-point-of-failure tail. When a link between
two switches flips `up`/`down`, an Azure Function recomputes reachability
from the gateway (BFS over `up` links only) and marks every cut-off switch
`unreachable` — and marks it `online` again the moment any path recovers.
Every transition lands in table storage and triggers an email alert.

This guide captures the full setup in the order it was actually built,
including every real error hit and how it was diagnosed — several of these
are non-obvious enough that reproducing this from scratch will very likely
hit them again.

---

## 0. Prerequisites

- Arch Linux (or any distro — adjust the install step accordingly)
- An Azure subscription (Azure for Students works, with one caveat — see
  the Table Storage note in step 4)

---

## 1. Install and configure Azure CLI

```bash
sudo pacman -Syu azure-cli
az version
az bicep install
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
az group create --name rg-refinery-blastradius --location eastus
```

> Region note: this subscription is restricted by a tenant-level policy to
> a specific region allow-list (`norwayeast`, `southcentralus`,
> `mexicocentral`, `northcentralus`, `eastus` — check yours with
> `az policy assignment list`, then `az rest --method get` on the
> `regionrestriction` assignment's `properties.parameters`). `eastus`
> worked for everything except Azure SQL Database — see step 4.

---

## 3. Register resource providers up front

```bash
az provider register --namespace Microsoft.DigitalTwins
az provider register --namespace Microsoft.Devices
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.Web
az provider register --namespace Microsoft.Insights
az provider register --namespace Microsoft.Communication
az provider register --namespace Microsoft.Authorization
```

```bash
az provider show --namespace <namespace> --query registrationState -o tsv
```

---

## 4. Deploy infrastructure with `main.bicep`

Everything — storage account, ADT instance, IoT Hub, Function App, table
storage, ACS email, the managed-identity role assignment — is defined in
`main.bicep` at the repo root. Deploying it is idempotent; re-running it
against existing resources updates them in place.

```bash
az deployment group create \
  --resource-group rg-refinery-blastradius \
  --template-file main.bicep
```

### Why Table Storage instead of Azure SQL Database

The original plan used Azure SQL Database for the alert log. It never
provisioned: `RegionDoesNotAllowProvisioning` across every tenant-allowed
region tried via CLI, and the Azure Portal's free-offer flow
(`aka.ms/azuresqlhub`) also failed in every region including one
(`australiaeast`) that isn't even in the tenant's region allow-list. This
turned out to be a known **Azure for Students** restriction — the offer
type blocks new SQL Database logical server creation subscription-wide,
independent of region. Table Storage reuses the storage account the
Function App already needs (`AzureWebJobsStorage`), needs no new resource
type, and just works. If you're not on Azure for Students, SQL Database
would work fine too — the trade-off is `table_client.py` would become a
`pymssql` wrapper instead (see the git history for the original code before
the pivot).

### Gotchas hit deploying this template

- **`InvalidLoginName`** — SQL Server (when we still had one) reserves
  `admin`, `administrator`, `sa`, `root`, `guest`, `public`,
  `information_schema`, `sys` as login names. Not relevant anymore post-pivot,
  but worth knowing if you ever add SQL back.
- **`InvalidDataLocation: DataLocation cannot be null or empty`** — the
  `Microsoft.Communication/emailServices` resource requires
  `properties.dataLocation` explicitly; it has no default.
- **`Invalid RetentionTimeInDays 0`** — the IoT Hub's F1 tier requires
  `eventHubEndpoints.events.retentionTimeInDays` to be exactly `1`; if it's
  never set explicitly it can resolve to `0` on redeploy and fail.
- **`RoleAssignmentExists`** — Azure role assignments are unique per
  `(scope, principalId, roleDefinitionId)` regardless of the assignment's
  own name/GUID. If the Function App's managed identity ever gets
  regenerated (e.g. a prior failed deployment recreated the Function App
  resource), the old assignment for the stale `principalId` becomes orphaned
  cruft, and bicep's deterministic `guid(...)`-named assignment for the
  *current* identity can collide with a pre-existing assignment under a
  different name covering the same triple. Fix: find and delete the stale
  assignment(s) with `az role assignment list --scope <adt-resource-id>`,
  then redeploy — bicep recreates it cleanly.
- **Doubled `sb://` in `EventHubConnectionString`** — the bicep template had
  `'Endpoint=sb://${iotHub.properties.eventHubEndpoints.events.endpoint}'`,
  but `.endpoint` **already includes** the `sb://` scheme prefix. Result:
  `Endpoint=sb://sb://...`, a malformed URI. The Function's Event Hub
  trigger failed to bind *silently* — no error in the host status, no
  exceptions logged anywhere — it just never received a single message.
  Caught by directly testing the connection string with the
  `azure-eventhub` Python SDK outside of Functions entirely (see step 10 for
  the full diagnostic path). Fixed by dropping the redundant `sb://` in the
  bicep string interpolation.
- **IoT Hub `$fallback` route disabled** — even with a correct connection
  string, messages ingressed into the hub successfully
  (`dailyMessageQuotaUsed` metric climbing) but never reached the built-in
  Event Hub-compatible endpoint (`d2c.endpoints.egress.builtIn.events`
  metric stuck at 0). Cause: `properties.routing.fallbackRoute.isEnabled`
  was `false` and no custom routes existed, so messages had nowhere to go
  and were silently dropped after ingress. `main.bicep` now sets this
  explicitly:
  ```bicep
  routing: {
    fallbackRoute: {
      source: 'DeviceMessages'
      condition: 'true'
      endpointNames: ['events']
      isEnabled: true
    }
  }
  ```

---

## 5. Grant yourself Digital Twins data-plane access

Control-plane ownership (from creating/owning the resource group) does
**not** include ADT data-plane permissions — that's a separate RBAC role,
needed for `seed_graph.py`, `reset_graph.py`, and any local `az dt` command:

```bash
az role assignment create \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Azure Digital Twins Data Owner" \
  --scope "$(az dt show -n adt-refinery-blastradius -g rg-refinery-blastradius --query id -o tsv)"
```

RBAC propagation can take a couple of minutes — if `az dt twin query` or the
Python SDK returns `Forbidden` right after granting the role, wait ~30s and
retry before assuming something else is wrong.

The Function App's own managed identity gets the same role automatically
via `main.bicep`'s `adtRoleAssignment` resource — that one only covers the
deployed app, not your own CLI session.

---

## 6. Build the switch mesh

`models/switch.json` defines the `Switch` DTDL model: `status`, `zone`,
`ipAddress`, `isGateway`, and a self-referencing `connectedTo` relationship
carrying a `linkStatus` property. Every mesh link needs **two** relationship
instances (A→B and B→A) since ADT relationships are directed.

```bash
cd cascade-function
export ADT_ENDPOINT="https://$(az dt show -n adt-refinery-blastradius -g rg-refinery-blastradius --query hostName -o tsv)"
pip install -r requirements.txt --break-system-packages
python seed_graph.py
```

This uploads the model and creates all 7 switches + mesh links from
`seed_graph.py`'s `SWITCHES`/`EDGES` dicts, idempotently (relationship IDs
are `f"{source}-to-{target}"`, not index-based, so re-running with a
reordered `EDGES` list doesn't create duplicates).

Verify:

```bash
az dt twin query --dt-name adt-refinery-blastradius \
  --query-command "SELECT * FROM digitaltwins"
```

Should return all 7 switches.

---

## 7. Publish the Function code

```bash
cd cascade-function
func azure functionapp publish func-refinery-cascade --python
```

Remote build installs `requirements.txt` server-side (a couple of minutes).
Should finish listing all three functions:

```
Functions in func-refinery-cascade:
    AlertHistory - [httpTrigger]
    GraphStatus - [httpTrigger]
    LinkEventProcessor - [eventHubTrigger]
```

---

## 8. Testing end to end

### 8a. Register the simulator's IoT Hub device

The simulator uses a single shared device — `LinkEventProcessor` reads
`sourceSwitch`/`targetSwitch` from the message body, not from IoT Hub device
identity, so one device covers the whole mesh:

```bash
az iot hub device-identity create --hub-name iot-refinery-blastradius --device-id dmz-simulator

az iot hub device-identity connection-string show \
  --hub-name iot-refinery-blastradius --device-id dmz-simulator -o tsv
```

### 8b. Run the simulator

```bash
pip install azure-iot-device
export IOT_DEVICE_CONNECTION_STRING="<connection string from above>"
python cascade-function/dmz_simulator.py
```

> **`ClientError: Error in the IoTHub client due to TLS exchanges`** — if
> your `python`/`pip` resolve into a conda environment (check with
> `which python`), its OpenSSL build may not see the system CA trust store
> that `paho-mqtt` (which `azure-iot-device` rides on) needs. Fix:
> ```bash
> export SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())")
> ```
> This points the stdlib `ssl` module at `certifi`'s bundled CA certs
> instead. Diagnosed by reproducing the connect call directly and printing
> the full exception chain (`e.__cause__`) — the top-level `ClientError` is
> a generic wrapper; the real cause was several layers down as
> `ssl.SSLCertVerificationError: unable to get local issuer certificate`.

The simulator heartbeats every 10s (`HEARTBEAT_INTERVAL_SEC`) and has a 15%
chance per tick of flapping a random link down, recovering it 15-45s later.

### 8c. Confirm it's actually reaching the Function

Two ways to check without relying on live log streaming, which **does not
work on the Linux Consumption plan** (`az webapp log tail` and
`func azure functionapp logstream` both 404 — this is a known platform
limitation, not a misconfiguration):

**Function execution count** (near-real-time, independent of Application
Insights):
```bash
az monitor metrics list \
  --resource "$(az functionapp show --name func-refinery-cascade --resource-group rg-refinery-blastradius --query id -o tsv)" \
  --metric "FunctionExecutionCount" --interval PT1M -o table
```

**Alert table** (the actual proof it worked):
```bash
KEY=$(az storage account keys list --account-name strefinerybr --resource-group rg-refinery-blastradius --query "[0].value" -o tsv)
az storage entity query --table-name SwitchAlerts --account-name strefinerybr --account-key "$KEY" -o table
```

Application Insights (`az monitor app-insights query`) is also available
but can lag well behind real-time — don't trust an empty result there as
proof nothing happened; cross-check with the metric/table above first.

### 8d. HTTP endpoints

```bash
curl https://func-refinery-cascade.azurewebsites.net/api/graphstatus | python3 -m json.tool
curl "https://func-refinery-cascade.azurewebsites.net/api/alerthistory?limit=10" | python3 -m json.tool
```

### 8e. Reset to a clean baseline

```bash
python cascade-function/reset_graph.py
```

Sets every link back to `up` and recomputes reachability (all switches
`online`).

---

## 9. React dashboard

```bash
cd refinery-dashboard
npm install
npm run dev -- --host
```

Open the printed local URL. Renders the mesh in a circular layout (no
fixed-tier layout needed at 7 nodes), colors nodes green/red by
`online`/`unreachable`, gives the gateway switch a blue border + `★` label
prefix, colors edges gray (`up`) or red-dashed (`down`), and overlays a
live `AlertPanel` polling `AlertHistory` every 5s.

> **Alert panel cut off / mispositioned** — not a window-manager quirk.
> `src/index.css` (leftover Vite scaffold CSS) caps `#root` at `1126px` and
> centers it (`margin: 0 auto`). The dashboard's outer container was
> `width: 100vw` — inside that centered box, a 100vw-wide element starts at
> `#root`'s inset left edge and extends a full viewport-width further
> right, pushing its actual right edge (and anything pinned to it, like the
> alert panel) off-screen on any viewport wider than 1126px. Fixed by using
> `position: fixed; inset: 0` on the container instead, which anchors it to
> the real viewport regardless of `#root`'s box.

---

## 10. CORS

```bash
az functionapp cors add \
  --name func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --allowed-origins "http://localhost:5173"
```

Add the deployed dashboard's real domain too once it's live (see step 12).

---

## 11. Debugging a deployed Function

Live log streaming doesn't work on Linux Consumption (see step 8c). In
rough order of reliability for figuring out *why* something isn't firing:

1. `FunctionExecutionCount` metric on the `Microsoft.Web/sites` resource —
   fastest signal, near-real-time, independent of App Insights.
2. The actual data the function should have produced (table rows, ADT
   twin state) — the ground truth.
3. `az functionapp function show --function-name <name>` — shows the
   resolved trigger binding config (useful for confirming app-setting
   placeholders like `%EVENT_HUB_NAME%` resolved to the value you expect).
4. Application Insights `traces`/`exceptions`/`requests` — can have several
   minutes of ingestion lag; don't treat an empty result as proof of
   nothing happening.
5. For anything Event Hub/IoT Hub-specific: test the exact connection
   string directly with the `azure-eventhub` SDK's `EventHubConsumerClient`,
   completely outside of Functions. This isolates "is the connection
   string/entity/permissions actually correct" from "is the Functions
   binding layer working" — this is what caught both the doubled `sb://`
   bug and would have caught the disabled fallback route too, if the IoT
   Hub-side metrics (`dailyMessageQuotaUsed` vs
   `d2c.endpoints.egress.builtIn.events`) hadn't already made it obvious.

---

## 12. Deploying the dashboard — Azure Static Web Apps was blocked

The original plan was Azure Static Web Apps (free tier). It failed with:

```
(RequestDisallowedByAzure) Resource '...' was disallowed by Azure:
This policy maintains a set of best available regions where your
subscription can deploy resources...
```

Static Web Apps only supports 5 regions total (`centralus`, `eastus2`,
`westus2`, `westeurope`, `eastasia`) and every one was rejected on this
subscription — a tenant/management-group-level policy, common on
institutional Azure for Students accounts, not fixable by picking a
different region.

**Fallback: GitHub Pages**, via `.github/workflows/deploy-dashboard.yml`
(GitHub Actions, triggers on changes under `refinery-dashboard/`). Tell
Vite the app is served from a subpath in `vite.config.js`:

```js
export default defineConfig({
  plugins: [react()],
  base: '/refinery-cloud/',  // must match the repo name exactly
})
```

Live at `https://RDG0818.github.io/refinery-cloud/`. Add that origin to
CORS (scheme + host only, no path):

```bash
az functionapp cors add \
  --name func-refinery-cascade \
  --resource-group rg-refinery-blastradius \
  --allowed-origins "https://RDG0818.github.io"
```

---

## Cost notes

- **IoT Hub F1, Function App Consumption plan**: permanently free within
  their grants (8,000 msgs/day; 1M executions + 400,000 GB-s/month). This
  project uses a negligible fraction of either.
- **Storage account (including Table Storage)**: no free tier, but
  fractions of a cent/month at this data volume.
- **Azure Communication Services Email**: pay-per-email beyond a small free
  grant; at demo volume, effectively free.
- **Azure Digital Twins**: **no free tier** — consumption pricing across
  Operations (~$2.50/million), Messages (~$1/million), Query Units
  (~$0.50/million). Manual/occasional testing is pennies total. Avoid
  leaving a dashboard **polling ADT continuously and unattended** — stop it
  when not actively demoing.
- Azure for Students has no card on file — the subscription disables at
  credit exhaustion rather than silently charging. A budget alert is still
  worth setting:

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

- Authentication (deliberately deferred)
