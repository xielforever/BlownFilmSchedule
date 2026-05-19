# Demo Scenario

This project now includes a small deterministic scheduling demo that is separate
from the 232-order pressure scenario.

## Apply demo data

```bash
python scripts/seed_demo.py apply
```

What this does:

- Saves the current active run and order/machine statuses to
  `output/demo_seed_snapshot.json`.
- Temporarily marks non-demo orders as `CANCELLED`.
- Temporarily marks non-demo machines as `OFFLINE`.
- Inserts 4 demo machines and 9 demo orders:
  - 8 feasible orders are scheduled into a new active run.
  - `DEMO-BLOCKED` is inserted as a configurable infeasible sample.
- Inserts a maintenance window and a downtime event so the Gantt chart can show
  production, setup, maintenance, downtime, and idle explanations.

Open:

- `http://localhost:3000/dashboard`
- `http://localhost:3000/gantt`
- `http://localhost:3000/orders?q=DEMO`
- `http://localhost:3000/config?tab=orders&order=DEMO-BLOCKED`

## Demonstrate failure fallback

Use this variant when you want the Dashboard "Run Schedule" button to fail
against the blocked order while the current active demo run remains visible:

```bash
python scripts/seed_demo.py apply --blocked-pending
```

Then click `Run Schedule` on the Dashboard. The expected story is:

- The last trigger fails because `DEMO-BLOCKED` has no eligible machine.
- The Dashboard explains that it is still displaying the current active run.
- The failure list links back to order configuration for repair.

## Restore previous data

```bash
python scripts/seed_demo.py restore
```

This removes demo rows, restores the previous active run, and restores the
saved order/machine statuses from `output/demo_seed_snapshot.json`.

## Check current demo state

```bash
python scripts/seed_demo.py status
```
