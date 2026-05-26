# Solver Benchmark Report

- Status: PASS
- Generated at: 2026-05-25T23:49:56Z
- Cases: 1 total, 1 passed, 0 failed

## Cases

| Case | Status | Passed | Scheduled | Deferred | Late | Weighted Tardiness | Setup Mins | Wall Time | Solver Budget | Arc Count | Pruned Arcs | Arc Pruning Strategy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fast-300 | UNPUBLISHABLE | True | 300 | 0 | 84 | 879600 | 9360 | 114.227 | 114.000 | 23936 | 338468 | due_window_mins=4320, due_window_top_k=16, enabled=True, max_setup_time_mins=999, same_cleanroom_top_k=16, same_material_family_top_k=16, top_k_per_order=32 |

## Baseline Metrics

| Case | Solver Status | Wall Time | Gap | Late | Weighted Tardiness | Setup Mins | Cleaning Required | Cleaning Disabled | Machines |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-300 | UNPUBLISHABLE | 114.227 | 1.000 | 84 | 879600 | 9360 | 4 | 0 | 4 |

## Machine Model Sizes

| Case | Machine | Eligible Orders | Assignments | Optional Candidates | Arcs | Pruned Arcs | Setup Cache |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-300 | LINE-B01 | 300 | 300 | 60 | 5984 | 84617 | 90000 |
| fast-300 | LINE-B02 | 300 | 300 | 60 | 5984 | 84617 | 90000 |
| fast-300 | LINE-B03 | 300 | 300 | 60 | 5984 | 84617 | 90000 |
| fast-300 | LINE-B04 | 300 | 300 | 60 | 5984 | 84617 | 90000 |

## Deferred Reasons

No deferred orders were produced by these benchmark cases.

## Profile Acceptance

| Profile | Cases | Passed | Failed | Max Wall Time | Max Gap | Min Scheduled Ratio | Acceptance Policy | Deferred Reasons | Failed Checks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| fast | 1 | 1 | 0 | 114.227 | 1.000 | 1.000 | max_gap=None, max_late_order_count=None, max_total_setup_time_mins=None, max_wall_time_seconds=120.0, max_weighted_tardiness=None, min_scheduled_ratio=1.0, profile=fast | - | - |

## Scale Acceptance

| Orders | Cases | Comparisons | Passed | Failed | Max Wall Time | Min Scheduled Ratio | Max Arcs | Max Pruned Arcs | Failed Checks |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 300 | 1 | 0 | 1 | 0 | 114.227 | 1.000 | 23936 | 338468 | - |
