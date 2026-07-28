# Refinery DMZ Switch Monitor

Simulates a 7-switch mesh in a refinery's DMZ/OT/IT network on Azure Digital Twins. Kill a link and an Azure Function figures out who's still reachable from the gateway, flags anything cut off, and flips it back once a path returns. Every flip gets logged and emailed.

**Live demo:** https://RDG0818.github.io/refinery-cloud/

## How it fits together

Simulated link events go into IoT Hub. `LinkEventProcessor` picks them up, patches the twin graph in Azure Digital Twins, and re-derives reachability from the gateway switch. Anything that changes state gets a row in Table Storage (`SwitchAlerts`) and an email via Azure Communication Services. Two more functions, `GraphStatus` and `AlertHistory`, just serve that state as JSON. The React dashboard polls both and draws the mesh with react-flow.

## Stack

Azure Digital Twins, IoT Hub, Azure Functions (Python), Table Storage, Azure Communication Services, Bicep, React + react-flow, GitHub Pages.

## Setup

See [`SETUP_GUIDE.md`](SETUP_GUIDE.md).

