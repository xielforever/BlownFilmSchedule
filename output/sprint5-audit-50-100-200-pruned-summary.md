# Solver Benchmark Report

- Status: PASS
- Generated at: 2026-05-25T23:47:47Z
- Cases: 3 total, 3 passed, 0 failed

## Cases

| Case | Status | Passed | Scheduled | Deferred | Late | Weighted Tardiness | Setup Mins | Wall Time | Solver Budget | Arc Count | Pruned Arcs | Arc Pruning Strategy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fast-50 | UNPUBLISHABLE | True | 50 | 0 | 0 | 0 | 1590 | 114.095 | 114.000 | 3936 | 6468 | due_window_mins=4320, due_window_top_k=16, enabled=True, max_setup_time_mins=999, same_cleanroom_top_k=16, same_material_family_top_k=16, top_k_per_order=32 |
| fast-100 | UNPUBLISHABLE | True | 100 | 0 | 0 | 0 | 3180 | 114.131 | 114.000 | 7936 | 32868 | due_window_mins=4320, due_window_top_k=16, enabled=True, max_setup_time_mins=999, same_cleanroom_top_k=16, same_material_family_top_k=16, top_k_per_order=32 |
| fast-200 | UNPUBLISHABLE | True | 200 | 0 | 0 | 0 | 6360 | 114.215 | 114.000 | 15936 | 145668 | due_window_mins=4320, due_window_top_k=16, enabled=True, max_setup_time_mins=999, same_cleanroom_top_k=16, same_material_family_top_k=16, top_k_per_order=32 |

## Baseline Metrics

| Case | Solver Status | Wall Time | Gap | Late | Weighted Tardiness | Setup Mins | Cleaning Required | Cleaning Disabled | Machines |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-50 | UNPUBLISHABLE | 114.095 | 4350.000 | 0 | 0 | 1590 | 1 | 0 | 1 |
| fast-100 | UNPUBLISHABLE | 114.131 | 100.000 | 0 | 0 | 3180 | 2 | 0 | 2 |
| fast-200 | UNPUBLISHABLE | 114.215 | 1.000 | 0 | 0 | 6360 | 3 | 0 | 4 |

## Machine Model Sizes

| Case | Machine | Eligible Orders | Assignments | Optional Candidates | Arcs | Pruned Arcs | Setup Cache |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-50 | LINE-B01 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50 | LINE-B02 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50 | LINE-B03 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50 | LINE-B04 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-100 | LINE-B01 | 100 | 100 | 20 | 1984 | 8217 | 10000 |
| fast-100 | LINE-B02 | 100 | 100 | 20 | 1984 | 8217 | 10000 |
| fast-100 | LINE-B03 | 100 | 100 | 20 | 1984 | 8217 | 10000 |
| fast-100 | LINE-B04 | 100 | 100 | 20 | 1984 | 8217 | 10000 |
| fast-200 | LINE-B01 | 200 | 200 | 40 | 3984 | 36417 | 40000 |
| fast-200 | LINE-B02 | 200 | 200 | 40 | 3984 | 36417 | 40000 |
| fast-200 | LINE-B03 | 200 | 200 | 40 | 3984 | 36417 | 40000 |
| fast-200 | LINE-B04 | 200 | 200 | 40 | 3984 | 36417 | 40000 |

## Deferred Reasons

No deferred orders were produced by these benchmark cases.

## Profile Acceptance

| Profile | Cases | Passed | Failed | Max Wall Time | Max Gap | Min Scheduled Ratio | Acceptance Policy | Deferred Reasons | Failed Checks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| fast | 3 | 3 | 0 | 114.215 | 4350.000 | 1.000 | max_gap=None, max_late_order_count=None, max_total_setup_time_mins=None, max_wall_time_seconds=120.0, max_weighted_tardiness=None, min_scheduled_ratio=1.0, profile=fast | - | - |

## Scale Acceptance

| Orders | Cases | Comparisons | Passed | Failed | Max Wall Time | Min Scheduled Ratio | Max Arcs | Max Pruned Arcs | Failed Checks |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 50 | 1 | 0 | 1 | 0 | 114.095 | 1.000 | 3936 | 6468 | - |
| 100 | 1 | 0 | 1 | 0 | 114.131 | 1.000 | 7936 | 32868 | - |
| 200 | 1 | 0 | 1 | 0 | 114.215 | 1.000 | 15936 | 145668 | - |
