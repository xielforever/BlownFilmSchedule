# Solver Benchmark Report

- Status: PASS
- Generated at: 2026-05-25T23:41:52Z
- Cases: 2 total, 2 passed, 0 failed

## Cases

| Case | Status | Passed | Scheduled | Deferred | Late | Weighted Tardiness | Setup Mins | Wall Time | Solver Budget | Arc Count | Pruned Arcs | Arc Pruning Strategy |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fast-50-pruning-off | UNPUBLISHABLE | True | 50 | 0 | 0 | 0 | 1590 | 114.144 | 114.000 | 10404 | 0 | due_window_mins=4320, due_window_top_k=16, enabled=False, max_setup_time_mins=999, same_cleanroom_top_k=16, same_material_family_top_k=16, top_k_per_order=32 |
| fast-50-pruning-on | UNPUBLISHABLE | True | 50 | 0 | 0 | 0 | 1590 | 114.095 | 114.000 | 3936 | 6468 | due_window_mins=4320, due_window_top_k=16, enabled=True, max_setup_time_mins=999, same_cleanroom_top_k=16, same_material_family_top_k=16, top_k_per_order=32 |

## Baseline Metrics

| Case | Solver Status | Wall Time | Gap | Late | Weighted Tardiness | Setup Mins | Cleaning Required | Cleaning Disabled | Machines |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-50-pruning-off | UNPUBLISHABLE | 114.144 | 3009.000 | 0 | 0 | 1590 | 1 | 0 | 1 |
| fast-50-pruning-on | UNPUBLISHABLE | 114.095 | 4380.000 | 0 | 0 | 1590 | 1 | 0 | 1 |

## Machine Model Sizes

| Case | Machine | Eligible Orders | Assignments | Optional Candidates | Arcs | Pruned Arcs | Setup Cache |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast-50-pruning-off | LINE-B01 | 50 | 50 | 10 | 2601 | 0 | 2500 |
| fast-50-pruning-off | LINE-B02 | 50 | 50 | 10 | 2601 | 0 | 2500 |
| fast-50-pruning-off | LINE-B03 | 50 | 50 | 10 | 2601 | 0 | 2500 |
| fast-50-pruning-off | LINE-B04 | 50 | 50 | 10 | 2601 | 0 | 2500 |
| fast-50-pruning-on | LINE-B01 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50-pruning-on | LINE-B02 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50-pruning-on | LINE-B03 | 50 | 50 | 10 | 984 | 1617 | 2500 |
| fast-50-pruning-on | LINE-B04 | 50 | 50 | 10 | 984 | 1617 | 2500 |

## Deferred Reasons

No deferred orders were produced by these benchmark cases.

## Profile Acceptance

| Profile | Cases | Passed | Failed | Max Wall Time | Max Gap | Min Scheduled Ratio | Acceptance Policy | Deferred Reasons | Failed Checks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| fast | 2 | 2 | 0 | 114.144 | 4380.000 | 1.000 | max_gap=None, max_late_order_count=None, max_total_setup_time_mins=None, max_wall_time_seconds=120.0, max_weighted_tardiness=None, min_scheduled_ratio=1.0, profile=fast | - | - |

## Scale Acceptance

| Orders | Cases | Comparisons | Passed | Failed | Max Wall Time | Min Scheduled Ratio | Max Arcs | Max Pruned Arcs | Failed Checks |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 50 | 2 | 1 | 2 | 0 | 114.144 | 1.000 | 10404 | 6468 | - |

## Arc Pruning Comparisons

| Group | Passed | Baseline | Pruned | wall_time_seconds_delta | late_order_count_delta | weighted_tardiness_delta | total_setup_time_mins_delta | arc_count_delta | pruned_arc_count_delta | Failed Checks |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fast-50 | True | fast-50-pruning-off | fast-50-pruning-on | -0.049 | 0 | 0 | 0 | -6468 | 6468 | - |
