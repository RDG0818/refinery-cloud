# Refinery DMZ Switch Monitor

Network monitoring simulator built on Azure Digital Twins. Models a flat mesh
of 7 network switches in a refinery's DMZ/OT/IT segments. When a link between
two switches goes down, an Azure Function recomputes reachability from the
gateway switch (BFS over `up` links) and marks every switch that's been cut
off `unreachable` — and marks it `online` again the moment a path comes back,
no matter which link recovers. Every transition is logged to table storage
and triggers an email alert. A React dashboard visualizes the mesh live.

**Live demo:** https://RDG0818.github.io/refinery-cloud/

## Architecture

```
dmz_simulator.py (local) --> IoT Hub --> Function: LinkEventProcessor --> Azure Digital Twins
                                                       |                        ^
                                                       v                        |
                                          Table Storage (SwitchAlerts)          |
                                                       |                        |
                                                       v                        |
                                          ACS Email (unreachable/recovered)     |
                                                                                 |
React dashboard <-- Function: GraphStatus, AlertHistory <----------------------+
```

- **Azure Digital Twins** — stores the switch graph (models, twins, `connectedTo` relationships)
- **IoT Hub** — ingests simulated link up/down telemetry
- **Azure Functions**
  - `LinkEventProcessor` — event-triggered; patches the affected link, recomputes reachability from the gateway switch, logs + emails any transitions
  - `GraphStatus` — HTTP-triggered; returns the current graph (twins + relationships, including `linkStatus`) as JSON
  - `AlertHistory` — HTTP-triggered; returns recent alert rows from Table Storage
- **Table Storage** — `SwitchAlerts` table, one row per `unreachable`/`recovered` transition
- **Azure Communication Services (Email)** — sends an alert email per transition, from a free Azure Managed Domain
- **React + react-flow** — polls `GraphStatus` every 3s (mesh) and `AlertHistory` every 5s (alert feed)

## Repo structure

```
models/switch.json         DTDL model: Switch twin + self-referencing connectedTo relationship
main.bicep                  Full infra as code (ADT, IoT Hub, Storage, Function App, ACS)
cascade-function/           Azure Functions app
  function_app.py             LinkEventProcessor, GraphStatus, AlertHistory
  cascade_logic.py            get_adt_client()
  reachability_logic.py       BFS reachability recompute (core logic)
  table_client.py             Table Storage alert log (insert/fetch)
  email_client.py             ACS email alerts
  seed_graph.py                Builds the 7-switch mesh in ADT (models + twins + relationships)
  reset_graph.py               Resets every link to `up` and recomputes reachability
  dmz_simulator.py             Standalone IoT Hub telemetry generator (not deployed, local only)
refinery-dashboard/         React dashboard (mesh view + AlertPanel)
SETUP_GUIDE.md               Full step-by-step setup, exact commands, deployment gotchas
```

## Stack

Azure Digital Twins · IoT Hub · Azure Functions (Python) · Table Storage ·
Azure Communication Services (Email) · Bicep · React · react-flow · GitHub Pages

## Setup

See [`SETUP_GUIDE.md`](SETUP_GUIDE.md) for the full walkthrough, including
exact `az` CLI commands and every gotcha hit along the way.

## Cost

Runs within free tiers except Azure Digital Twins, which is consumption-based
(no free tier). Occasional/manual use is pennies/month. See cost notes in
`SETUP_GUIDE.md`.

## Status

Working end-to-end, deployed for real on Azure: simulated telemetry → link
event → reachability recompute (including recovery, not just failure) →
table storage alert row → email → dashboard. Infra fully captured in
`main.bicep`. Not yet built: authentication (deliberately deferred).
