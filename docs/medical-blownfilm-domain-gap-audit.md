# Medical Blown Film APS Domain Gap Audit

**Generated**: 2026-08-28  
**Status**: active  
**Scope**: Wave 1 — audit only; no solver/schema implementation changes in this document.  
**Source baseline**: `docs/medical-blownfilm-official-source-registry.md`

## 1. Executive Conclusion

The current project is already a mature APS prototype: CP-SAT scheduling, sequence-dependent setup, maintenance windows, material-ready time, cleanroom/width/thickness/layer screening, locked tasks, snapshots, diagnostics, configurable policy and publish governance are present.

The primary risk is no longer "missing features". The primary risk is **domain semantics not being carried consistently from master data into solver decisions**.

The most important findings are:

1. some medical/material classifications are inferred from supplier/grade text instead of authoritative grade qualification;
2. missing recipes can silently fall back to a synthetic material instead of being blocked;
3. recipe ratios exist in schema/snapshots but are not carried into solver objects;
4. production duration is still based on one machine-level constant kg/h;
5. material inventory/lot quantity is not a solver quantity constraint; only one order-level ready time is enforced;
6. machine eligibility lacks process route, polymer family, equipment-feature and validated-product qualification dimensions;
7. 3-layer ↔ 5-layer setup calculation truncates unmatched layers;
8. a rule described as GMP clearance is keyed by scheduling urgency/order class rather than a validated hygiene/qualification class;
9. some rules described as compliance/regulatory constraints (72 h continuous run, fixed weekly sanitation) have no authoritative source in the repository and must be treated as plant policy/simulation until an SOP proves otherwise;
10. input snapshots omit fields that affect setup/objective, allowing a draft to become stale without being detected.

## 2. Review Method

Each domain item is checked across six layers:

```text
External evidence / plant source
        ↓
Database schema
        ↓
In-memory model
        ↓
Eligibility / preprocessing
        ↓
CP-SAT constraint or objective
        ↓
Validation / KPI / diagnostics
```

A field is **not considered implemented** merely because it exists in the database or UI.

### Priority definition

| Priority | Meaning |
| --- | --- |
| `P0` | Can produce a business-invalid, medically invalid, materially impossible or materially misleading schedule. Must be resolved before calling the benchmark industrial-grade. |
| `P1` | Important for rolling scheduling accuracy, maintainability or plant realism. Should follow immediately after P0. |
| `P2` | Useful realism/optimization extension; not required to validate the first industrial scheduling core. |

## 3. P0 Findings

### P0-01 — Medical material category is inferred from supplier/grade text

**Current evidence**

`src/database.py::_save_raw_materials()` derives categories using name matching such as:

- contains `Borealis` → `MEDICAL_HIGH`
- contains `Dow` / `Bird` → `PACKAGING`
- otherwise → `MEDICAL_STD`

**Why this is invalid**

Medical suitability is grade- and end-use-specific. A supplier makes both medical and non-medical materials. Conversely, a technically suitable blown-film resin may explicitly prohibit medical applications.

**Official-source evidence**

See the source registry:

- Purell PE 2420 F / 3020K: manufacturer explicitly describes healthcare/pharmaceutical film use.
- Purell SP170G: healthcare use, but manufacturer also requires application discussion.
- Bormed DM55pharm: intended for evaluation in healthcare applications.
- Exact 5101: technically a blown-film resin but explicitly not intended for medical applications.

**Target design**

Replace inferred `material_category` with explicit fields:

```text
polymer_family
manufacturer
commercial_grade
manufacturer_application_status
plant_qualification_status
qualification_scope
source_id
source_revision
valid_from
valid_to
```

Recommended qualification state:

```text
APPROVED
CONDITIONAL
TECHNICAL_TRIAL_ONLY
EXCLUDED_MEDICAL
UNKNOWN
```

**Solver rule**

Medical commercial orders must never use `EXCLUDED_MEDICAL` or `UNKNOWN`. `TECHNICAL_TRIAL_ONLY` is allowed only for an explicit trial/validation scenario.

---

### P0-02 — Missing recipe silently falls back to `Standard_Med_LDPE`

**Current evidence**

Both Excel ingestion and DB order loading use a fallback equivalent to:

```python
recipes_map.get(product_type, ["Standard_Med_LDPE"])
```

`order_screening.py` blocks `missing_recipe` only when `recipe_materials` is empty. Because the fallback is non-empty, the intended blocker can be bypassed.

**Risk**

An order with missing/incorrect process master may be scheduled as a fake one-layer LDPE product.

**Target rule**

Missing recipe must produce:

```text
recipe_status = MISSING
screening_status = blocked
business_bucket = blocked_data_error
```

No synthetic material fallback is allowed in production scheduling.

---

### P0-03 — Recipe ratio is lost before the solver

**Current evidence**

- `recipes.ratio_pct` exists in the DB schema.
- process snapshots include `ratio_pct`.
- Excel `_parse_recipes()` returns only `List[str]` material grades.
- DB `_load_recipes_map()` selects only `product_type, layer, material_grade`.
- Excel-to-DB `_save_recipes()` inserts no `ratio_pct`.
- `ProductionOrderModel.recipe_materials` contains only material sequence.

**Risk**

The project cannot reliably calculate:

- layer-specific material requirement;
- material reservation by grade/lot;
- recipe-dependent output rate;
- layer transition losses;
- recipe revision equality;
- barrier-layer cost or qualification scope.

**Target model**

Use a structured recipe object:

```text
RecipeVersion
  recipe_version_id
  product_id
  process_route
  layer_count
  status
  valid_from
  valid_to

RecipeLayer
  layer_index
  extruder_position
  material_grade
  ratio_pct
  target_layer_thickness_um
```

The solver may still consume a flattened immutable snapshot, but ratios must be preserved.

---

### P0-04 — Production duration uses a single machine-level kg/h

**Current evidence**

`BlownFilmMachineModel.calculate_duration()` computes:

```text
quantity × 60 / hourly_output_kg
```

`scheduler.py` uses that function directly for the machine/order `duration_cache`.

**Why this is insufficient**

Official equipment/material sources prove that process route, layer structure and material family vary materially. A mono PE product, five-layer PE/tie/EVOH/tie/PE product and PA barrier product cannot safely be assumed to run at one identical standard rate merely because they use the same line.

**Target design — first industrial version**

Do not introduce a complex physics model yet. Add an explicit capability table:

```text
machine_recipe_capability
  machine_id
  recipe_version_id
  eligible
  standard_rate_kg_h
  min_rate_kg_h
  max_rate_kg_h
  startup_rate_factor
  source_type
  source_id
  confidence
  valid_from
  valid_to
```

**Duration**

```text
run_minutes = ceil(net_production_kg / standard_rate_kg_h × 60)
```

Later MES history may replace/adjust `standard_rate_kg_h` with a learned rate distribution.

---

### P0-05 — Material constraint is time-only, not quantity/lot constrained

**Current evidence**

The DB contains `raw_materials` and `material_inventory`, but `ProductionOrderModel` carries only `material_available_mins` and CP-SAT only enforces:

```text
start >= material_available_mins
```

No material-grade quantity balance or lot release state is part of the solver feasibility model.

**Risk**

Two orders can both be scheduled against the same limited stock because no shared material balance exists.

**Target scope**

For the first industrial version, full lot-to-task assignment inside CP-SAT is optional, but a pre-solve material reservation service is mandatory.

Minimum flow:

```text
recipe ratio
→ gross material demand
→ available released stock
→ inbound supply before planned start
→ reservation
→ earliest material feasible time
→ solver input
```

At minimum, preserve per-material shortage evidence instead of only one opaque `material_available_time`.

For medical production add lot states such as:

```text
RELEASED
QC_HOLD
QUARANTINE
REJECTED
TECHNICAL_TRIAL_ONLY
EXPIRED
```

---

### P0-06 — Machine eligibility is incomplete

**Current evidence**

`evaluate_machine_fit()` currently checks:

- cleanroom
- width
- thickness
- recipe layer count

The machine model contains no explicit:

- process route (`UPWARD_AIR`, `DOWNWARD_WATER_QUENCH`)
- polymer-family capability
- extruder/layer-position material capability
- corona equipment capability
- gauge-control / IBC / dosing capability
- medical release state
- validated product/recipe family

**Official-source evidence**

- W&H publishes material families and layer architectures as independent line dimensions.
- Rajoo AQUAFLEX establishes downward water-quench as a distinct process route.
- TekniPlex provides a real healthcare five-layer ISO Class 7 capability example.

**Target capability layers**

```text
PhysicalCapability
ProcessCapability
MaterialCapability
QualityCapability
RegulatoryQualification
```

Hard eligibility must be the intersection of all applicable layers.

---

### P0-07 — 3-layer ↔ 5-layer setup ignores unmatched layers

**Current evidence**

`SetupCalculator.calculate_setup_time()` and scrap calculation use:

```python
num_layers = min(len(m_from), len(m_to))
```

Only the shared prefix is evaluated.

**Risk**

For 3 → 5 transition, the new fourth/fifth extruder states may contribute zero setup and zero scrap even though they require activation/loading/purge/stabilization. The reverse transition can also omit shutdown/purge effects.

**Target algorithm**

Normalize both recipes to machine extruder positions and compare through the maximum relevant position:

```text
EMPTY → MATERIAL
MATERIAL → EMPTY
MATERIAL_A → MATERIAL_B
MATERIAL_A → MATERIAL_A
```

Setup time can still use parallel max across extruder cleaning operations; scrap remains additive where physically appropriate.

Add dedicated regression cases for 3→5, 5→3, inactive→active and active→inactive transitions.

---

### P0-08 — `gmp_clearance_matrix` is keyed by scheduling order class

**Current evidence**

The matrix is keyed by `from_order_class` / `to_order_class`; `SetupCalculator` feeds `NORMAL`, `URGENT`, `SAMPLE` from `ProductionOrderModel.order_class` into GMP clearance lookup.

**Domain problem**

Urgency is a scheduling priority. A hygiene/cleaning/validation requirement should normally be determined by product/material/contact/qualification risk, not whether the order is urgent.

No official source in the source registry establishes a universal GMP cleaning matrix by `URGENT/NORMAL/SAMPLE`.

**Target separation**

Keep:

```text
order_class = URGENT / NORMAL / SAMPLE
```

for priority only.

Add a separate validated attribute, for example:

```text
hygiene_change_class
cleaning_validation_group
product_contact_risk_group
campaign_family
```

The clearance matrix must be keyed by the plant-approved cleaning taxonomy.

---

### P0-09 — 72 h cleaning and weekly sanitation are not proven universal regulatory rules

**Current evidence**

`src/config.py` declares:

- `CONTINUOUS_RUN_LIMIT_MINUTES = 4320` (72 h)
- mandatory cleaning 90 min
- a fixed weekly microbiological sanitation/empty-run window

The code/document language treats these as compliance/GMP controls.

**External evidence review**

ISO 11607 defines packaging-system/material requirements and validation context but does not prescribe this blown-film 72 h interval. ISO 14644 defines cleanroom classification by particle concentration. EU GMP Annex 1 applies to sterile medicinal-product manufacture where applicable and requires validated contamination-control practices, but it should not be converted into a universal blown-film 72 h rule without an applicable plant SOP/validation source.

**Decision**

Until plant evidence exists, reclassify these values as:

```text
source_type = SIMULATED or PLANT_SOP
regulatory_claim = false
```

If a real factory SOP later defines 72 h / 90 min, the rule can become a hard plant compliance constraint with SOP identifier, revision and effective date.

---

### P0-10 — Snapshot does not cover all solver-relevant order fields

**Current evidence**

`ORDER_SNAPSHOT_FIELDS` includes width, thickness, quantity, cleanroom, order class, due date, material-ready time, status and priority override, but omits fields such as:

- `corona_req`
- `core_size_inch`
- customer/customer class source used for tardiness priority

Yet corona/core changes alter setup time and customer class can alter tardiness weighting.

**Risk**

A draft may remain "not stale" even though a field affecting the objective or setup model changed.

**Target rule**

Every field that can change:

```text
eligibility
processing duration
setup
material demand
objective
lock behavior
```

must be represented in the input snapshot or referenced version hash.

---

## 4. P1 Findings

### P1-01 — Recipe revision / approval lifecycle is missing

Current uniqueness is effectively `product_type + layer`, not a versioned approved process definition.

Add:

```text
recipe_version_id
revision
status: DRAFT / VALIDATED / RELEASED / RETIRED
valid_from / valid_to
approved_by / approved_at
change_reason
```

A schedule run must reference the exact recipe version.

### P1-02 — Plan stability is not an optimization objective

Locked tasks are well protected, but unlocked future tasks can be reassigned/resequenced freely.

Add rolling-plan penalties after service-level objectives:

```text
machine_change_penalty
start_time_shift_penalty
sequence_change_penalty
```

Compare against a published/reference schedule snapshot.

### P1-03 — Legacy cleanroom labels need canonical source-aware representation

Current values are `Class_10K` / `Class_100K`.

Keep legacy aliases for UI/import compatibility, but store canonical fields such as:

```text
cleanroom_standard = ISO_14644_1
cleanroom_iso_class
qualification_status
qualification_valid_until
legacy_label
```

Do not assert one cleanroom class for every medical product; required class is product/process/plant specific.

### P1-04 — Excel initial material state broadcasts one grade to every layer

`_parse_machines()` reads one initial material and broadcasts it across machine layer count.

This is unsuitable for a real barrier line state.

DB `machine_current_state.current_material_lanes` already points in the right direction. Make layer/extruder current state explicit for all ingestion paths.

### P1-05 — Die-change rule has weak reachability semantics

Setup calls `get_width_change_time(delta, exceeds)` where `exceeds` is `target_width > machine.max_width`; eligibility already rejects such an assignment.

Therefore `die_change_time` does not represent a real selectable die-range transition.

If die changes are in scope, model actual die tooling/resource/configuration:

```text
die_id
supported_width_range
supported_bur_range
change_time
availability
```

Otherwise remove the misleading rule from the scheduling core.

### P1-06 — Machine feature fields can exist without eligibility enforcement

Example: order has `corona_req`, but the machine does not expose a `corona_capable` hard capability. Current setup logic merely charges time if corona state changes.

Add feature eligibility before using feature state setup.

### P1-07 — Same-material setup cannot distinguish lot change vs same running lot

`same_material_time` is described as same material / batch change, but recipe objects contain grade only, not active lot.

Keep a plant-configured same-grade product change if operationally required, but do not label it "lot change" unless lot state is known.

### P1-08 — Quality capability is not represented in eligibility

APS should not solve detailed lab tests, but a validated capability gate is needed for product families requiring properties such as barrier/OTR/WVTR, puncture or optical performance.

Recommended abstraction:

```text
machine_recipe_qualification
  quality_status
  validation_protocol_id
  valid_from
  valid_to
```

The quality test values remain MES/QMS data; APS consumes only the released capability status.

### P1-09 — Source/provenance is not first-class master data

The project's current concern is traceability of simulated vs official values. Add provenance at the schema level instead of keeping it only in documentation.

Minimum:

```text
source_type
source_id
source_revision
valid_from
valid_to
confidence
approved_by
```

### P1-10 — Material demand and scrap are not closed-loop quantities

`actual_material_required_kg = order quantity + scrap` is computed after schedule extraction. Since material quantity is not reserved in the solver/pre-solve balance, the schedule cannot prove that gross demand is available.

Move gross-demand estimation before material feasibility screening.

## 5. P2 Findings

### P2-01 — Inline slitting capability is currently a largely disconnected field

`max_slitting_lanes` exists but no order-level lane demand or splitting model is visible in core eligibility.

Keep it out of MVP hard constraints unless inline slitting is truly part of the blown-film scheduling scope.

### P2-02 — Holding / earliness cost may be useful later

The solver intentionally left-packs tasks. This improves compactness but can produce much earlier completion than operationally needed.

For later production-planning realism consider soft earliness/inventory penalties after service/setup/stability objectives.

### P2-03 — Learned uncertainty bands

Future MES learning should store rate/setup distributions rather than only averages:

```text
p10 / median / p90
sample_count
last_observed
```

Use conservative rate percentiles for high-risk commitments.

### P2-04 — Roll / winder constraints

If the customer demonstration later requires roll-level realism, add max roll weight/diameter, core inventory, mother/child roll and reel-change events. Do not introduce these into the current core unless they change real line feasibility.

## 6. Current → Target Crosswalk

| Domain | Current | Solver impact now | Target | Priority |
| --- | --- | --- | --- | --- |
| Width | machine min/max | hard | retain | KEEP |
| Thickness | machine min/max | hard | retain | KEEP |
| Layer count | recipe list length ≤ machine layer count | hard | explicit machine-recipe qualification / extruder positions | P0/P1 |
| Cleanroom | legacy 10K/100K | hard | ISO-aware + plant qualification | P1 |
| Process route | absent | none | upward air / downward water quench etc. | P0 |
| Material family capability | absent | none | machine/material capability | P0 |
| Medical material eligibility | inferred category | not robust | grade qualification workflow | P0 |
| Recipe ratio | schema/snapshot only | lost | solver-visible recipe version/layers | P0 |
| Production rate | machine constant | duration | Machine × Recipe rate | P0 |
| Inventory | inventory table + ready time | ready-time only | grade/lot reservation and shortage evidence | P0 |
| Setup material | directional matrix | hard gap | keep, add inactive-layer transitions | P0 |
| Width/thickness setup | matrix | hard gap | retain with plant source | KEEP/P1 |
| Corona | order state/setup | setup only | add machine capability | P1 |
| Core size | order state/setup | setup only | add machine supported cores if needed | P1 |
| GMP clearance | keyed by urgency | setup | replace with cleaning/validation class | P0 |
| Maintenance | fixed/DB intervals | hard no-overlap | retain; source each rule | KEEP |
| Continuous run | 72 h post-solve blocker | publish blocker | plant-SOP-backed only | P0 governance |
| Locked tasks | implemented | hard | retain | KEEP |
| Plan stability | absent | none | reference-plan soft penalties | P1 |
| Diagnostics | strong | post/pre-solve | extend new blockers | KEEP |
| Provenance | mostly documentation | none | first-class master data | P1 |

## 7. Target Domain Model Boundary

The next implementation wave should remain **blown-film APS**, not expand into the entire converting chain.

### In scope

```text
Equipment
  machine / extruder positions / process route / current state

Material
  grade / qualification / lot availability / release status

Product & Recipe
  product / recipe version / layers / ratios / validation status

Order
  quantity / spec / due / priority / material demand / planning state

Process
  machine-recipe rate / setup / purge / scrap / cleaning

Execution Calendar
  maintenance / breakdown / quality hold / locks / frozen intervals

APS
  eligibility / hard constraints / lexicographic objectives / replanning

Evaluation
  feasibility / tardiness / setup / scrap / stability / runtime
```

### Out of scope for this integration wave

- printing
- bag making
- terminal sterilization scheduling
- laboratory detailed test scheduling
- downstream logistics routing

These may provide order qualification inputs but should not enlarge the CP-SAT core yet.

## 8. Recommended Target Objective Hierarchy

Do not replace the current lexicographic approach with one giant weighted sum.

Recommended hierarchy:

```text
Level 0  Hard feasibility / qualification / locks
Level 1  Critical service commitments
Level 2  Weighted tardiness + late-order count
Level 3  Rolling-plan stability
Level 4  Sequence-dependent setup time
Level 5  Setup/startup material loss
Level 6  Secondary machine preference / balance / earliness
```

`Level 3` should be introduced only after P0 domain correctness is complete.

## 9. Implementation Waves

### Wave 1 — COMPLETE BY THIS DOCUMENT

- official source policy established;
- source registry established;
- repository-to-domain crosswalk completed;
- P0/P1/P2 gaps identified;
- no code changed.

### Wave 2 — Domain Model / Schema

Implement first:

1. provenance fields / source registry linkage;
2. material qualification state;
3. recipe version + recipe layers + ratio;
4. machine process/material/feature capability;
5. machine-recipe qualification and standard rate;
6. cleaning/validation class separate from order urgency;
7. released material-lot/reservation model.

Preserve compatibility views/adapters for current API where practical.

### Wave 3 — Solver Correctness

Implement in this order:

1. remove missing-recipe synthetic fallback;
2. replace supplier-name medical inference;
3. new eligibility gates;
4. Machine × Recipe duration;
5. 3↔5 layer setup transitions;
6. material gross-demand feasibility;
7. snapshot coverage fixes;
8. new diagnostics and publish blockers.

### Wave 4 — Rolling Optimization

- reference schedule / stability penalties;
- learned rate/setup statistics;
- benchmark scenarios and sensitivity testing.

## 10. Required Benchmark Scenarios After P0

The benchmark must no longer be only random order volume.

Create deterministic cases for:

1. missing recipe — must block;
2. Explicit medical-excluded grade — must block;
3. technical-only barrier material on commercial medical order — must block unless validation scenario;
4. water-quench PP order on upward-air line — must block;
5. 3→5 layer transition — extra layer activation setup included;
6. 5→3 layer transition — deactivation/purge rule included;
7. same quantity/product on two machines with different recipe rates — choose correct capacity tradeoff;
8. two orders competing for insufficient material stock — cannot both be materially feasible;
9. QC-held lot — unavailable;
10. material arrival during planning horizon — earliest feasible start propagated;
11. maintenance intersection — no overlap;
12. locked running task — no movement;
13. previous published future task — stability cost measured;
14. cleanroom-qualified vs unqualified machine;
15. recipe revision change — old draft becomes stale;
16. corona-required product on non-corona machine — block;
17. plant cleaning SOP enabled/disabled source governance;
18. infeasible order diagnostic explains exact blocker.

## 11. Acceptance Criteria for "Industrial Benchmark v2"

Before describing the dataset/solver as an industrial medical blown-film benchmark, all must hold:

- zero P0 findings remain open;
- every hard compliance/medical qualification rule has source provenance;
- no medical suitability is inferred from supplier name;
- no missing recipe falls back to synthetic production data;
- recipe ratios survive DB → model → feasibility/material calculation;
- duration is machine-recipe-specific;
- process route is a hard eligibility dimension;
- material quantity feasibility is demonstrated, not only material-ready time;
- 3↔5 layer setup regression tests pass;
- snapshot stale validation covers every solver-relevant master/order field;
- benchmark contains deterministic domain cases in addition to load tests;
- hard-constraint violations = 0 on every publishable schedule.

## 12. Immediate Decision Record

For the next implementation wave:

- **Keep** the current CP-SAT architecture, two-phase/lexicographic strategy, locked-task protection, diagnostics, maintenance `NoOverlap`, policy snapshot concept and publish governance.
- **Do not** replace the project with the previously generated simulation workbook.
- **Use** the official source registry only to correct/extend master-data semantics and benchmark envelopes.
- **Treat** plant-specific setup/rate/cleaning values as `PLANT_MASTER`, `PLANT_SOP`, `ENGINEERING`, `LEARNED` or `SIMULATED`; never relabel them as regulatory facts.
- **Next coding target**: Wave 2 domain/schema compatibility design before solver edits.
