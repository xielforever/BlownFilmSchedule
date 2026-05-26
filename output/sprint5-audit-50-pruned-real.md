# Solver Benchmark Report

- Status: PASS
- Generated at: 2026-05-25T23:37:52Z
- Cases: 1 total, 1 passed, 0 failed

## Cases

| Case | Status | Passed | Scheduled | Deferred | Late | Weighted Tardiness | Setup Mins | Wall Time | Solver Budget | Arc Count | Pruned Arcs | Arc Pruning Strategy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fast-50 | UNPUBLISHABLE | True | 50 | 0 | 0 | 0 | 1590 | 114.117 | 114.000 | 3936 | 6468 | due_window_mins=4320, due_window_top_k=16, enabled=True, max_setup_time_mins=999, same_cleanroom_top_k=16, same_material_family_top_k=16, top_k_per_order=32 |

## Baseline Metrics

| Case | Solver Status | Wall Time | Gap | Late | Weighted Tardiness | Setup Mins | Cleaning Required | Cleaning Disabled | Machines |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-50 | UNPUBLISHABLE | 114.117 | 6212.000 | 0 | 0 | 1590 | 1 | 0 | 1 |

## Machine Model Sizes

| Case | Machine | Eligible Orders | Assignments | Optional Candidates | Arcs | Pruned Arcs | Setup Cache |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-50 | LINE-B01 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50 | LINE-B02 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50 | LINE-B03 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50 | LINE-B04 | 50 | 50 | 10 | 984 | 1617 | 2500 |

## Deferred Reasons

No deferred orders were produced by these benchmark cases.

## Profile Acceptance

| Profile | Cases | Passed | Failed | Max Wall Time | Max Gap | Min Scheduled Ratio | Acceptance Policy | Deferred Reasons | Failed Checks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| fast | 1 | 1 | 0 | 114.117 | 6212.000 | 1.000 | max_gap=None, max_late_order_count=None, max_total_setup_time_mins=None, max_wall_time_seconds=120.0, max_weighted_tardiness=None, min_scheduled_ratio=1.0, profile=fast | - | - |

## Scale Acceptance

| Orders | Cases | Comparisons | Passed | Failed | Max Wall Time | Min Scheduled Ratio | Max Arcs | Max Pruned Arcs | Failed Checks |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 50 | 1 | 0 | 1 | 0 | 114.117 | 1.000 | 3936 | 6468 | - |
