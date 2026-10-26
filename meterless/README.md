# meterless/ — everything Meterless in ClinAssist AI

Meterless is the supervisor of ClinAssist: every request and every action (a script run, a Zetaris query,
a Nightshift/Nemotron call) is approved by Scout and recorded in the World Model before and after it runs.
Nothing reaches data or a model without Meterless knowing.

| Folder | What it is | Who wrote it |
|---|---|---|
| `vendor/world-model/` | Meterless World Model reference engine (event-sourced entity graph with provenance) | **Meterless** — copied unmodified, Apache-2.0 |
| `vendor/hmem/` | Meterless H-MEM reference engine (memory with hybrid retrieval and a trust ledger) | **Meterless** — copied unmodified, Apache-2.0 |
| `scout/` | Scout Intent: understands, guards and routes each request; signs an execution contract (`intents.json` = the registry) | ClinAssist team, implementing the published Scout Intent spec (Meterless ships no code for it) |
| `supervisor/` | The gate every action passes: checks it against the signed Scout contract, records request → decision → result in the World Model | ClinAssist team |
| `gateway/` | Local service (port 8090) that runs the vendored World Model and H-MEM for the Python app: run traces, script catalog memory | ClinAssist team, using the vendored engines |
| `world/` | Builds the patient-identity graph in the World Model and records reviewer decisions | ClinAssist team, using the vendored World Model |

Start the gateway (from the project folder): `npx.cmd tsx meterless/gateway/server.ts`
