# Medical Blown Film Official Source Registry

**Generated**: 2026-08-28  
**Status**: active  
**Purpose**: authoritative evidence baseline for APS domain modeling, simulation data, and future master-data integration.

## 1. Source Policy

This project must not treat all plausible engineering values as "official". Every APS datum should be classified by provenance.

| Source class | Meaning | Allowed use |
| --- | --- | --- |
| `STANDARD_REGULATOR` | ISO / FDA / official regulatory guidance | Defines scope, terminology, recognized standards, validation expectations. Do not invent numeric production constraints that the source does not specify. |
| `OEM_OFFICIAL` | Blown-film equipment OEM official product page / brochure | Defines equipment architecture, material/process capability envelope, layer counts, width ranges, screw/die options, process route. Do not treat configurable ranges as a specific plant machine nameplate. |
| `MATERIAL_OEM_OFFICIAL` | Resin producer official product page / TDS/PDS | Defines grade identity, intended application, typical properties and processing notes. "Healthcare application" is not equivalent to universal approval for every medical product. |
| `CONVERTER_OFFICIAL` | Healthcare film converter official production capability | Useful evidence for realistic cleanroom/process/product envelopes. It is facility-specific, not a universal regulatory requirement. |
| `PLANT_MASTER` | Actual factory approved machine/material/process master | Highest operational authority for the specific factory after internal validation. Must carry approver/version/effective date. |
| `PLANT_SOP` | Approved factory cleaning, changeover, release, maintenance SOP | Authority for plant-specific cleaning intervals, purge rules, qualification groups, hold/release logic. |
| `ENGINEERING` | Process engineer validated value | May drive APS after approval; must not be described as OEM/regulatory fact. |
| `LEARNED` | MES/history-derived value | May drive rate/setup models with sample count, validity window and confidence. |
| `SIMULATED` | Synthetic benchmark/demo datum | Allowed for testing only. Must be visibly labeled. |

### Precedence

For an actual factory, use this operational precedence:

`validated PLANT_MASTER / PLANT_SOP > plant-specific OEM nameplate or approved vendor document > generic OEM/material official envelope > ENGINEERING > LEARNED fallback policy > SIMULATED`

The lower-priority source must never silently overwrite a validated higher-priority source.

## 2. Standards and Regulatory References

### SRC-STD-ISO11607-1

- Organization: ISO
- Source: ISO 11607-1:2019, including Amendment 1:2023
- URL: https://www.iso.org/standard/70799.html
- Use: requirements/test-method framework for materials, sterile barrier systems and packaging systems for terminally sterilized medical devices.
- APS implication: packaging/product validation context can constrain which validated product/recipe routes are eligible.
- Do **not** infer: a universal cleanroom class, a universal 72-hour cleaning rule, specific blown-film output, or specific changeover time.

### SRC-REG-FDA-11607

- Organization: U.S. FDA
- Source: Recognized Consensus Standards — ISO 11607-1/2 including AMD1:2023
- URL: https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfstandards/results.cfm?referencenumber=11607&sortcolumn=pdd&start_search=1
- Use: confirms FDA recognition of the cited packaging standards.
- APS implication: regulatory qualification should be modeled separately from machine physical capability.

### SRC-STD-ISO14644-1

- Organization: ISO
- Source: ISO 14644-1:2015
- URL: https://www.iso.org/standard/53394.html
- Use: cleanroom air-cleanliness classification by airborne particle concentration.
- APS implication: store canonical ISO cleanroom class/qualified state instead of relying only on legacy `Class_10K` / `Class_100K` labels.
- Do **not** infer: that every medical blown-film order must be produced in one fixed ISO class.

### SRC-GMP-EU-ANNEX1

- Organization: European Commission
- Source: EudraLex Volume 4 Annex 1 — Manufacture of Sterile Medicinal Products
- URL: https://health.ec.europa.eu/medicinal-products/eudralex/eudralex-volume-4_en
- Use: sterile medicinal-product GMP context where applicable to the actual product/process.
- APS implication: only plant-approved SOP/validation rules derived for the applicable process may become hard scheduling rules.
- Do **not** infer: a generic 72-hour mandatory cleaning interval for blown-film equipment.

## 3. Equipment / Process References

### SRC-OEM-WH-VAREX2

- Organization: Windmöller & Hölscher
- Source: VAREX II official product page
- URL: https://www.wh.group/na/en/our_products/extrusion/blown_film_lines/varex_ii/
- Officially published envelope:
  - line width: 1300–3600 mm
  - film layers: 1 / 3 / 5 / 7 / 9 / 11
  - screw diameters: 50 / 60 / 70 / 90 / 105 / 120 / 135 mm
  - die diameters: 160–900 mm
  - raw materials include PE, PP, PA, EVOH and others
- APS use: proves that layer count, material family, screw/die configuration and line width are independent machine-capability dimensions.
- Do **not** infer: every W&H line has every option or one fixed kg/h rate.

### SRC-CONV-TEKNIPLEX-5L

- Organization: TekniPlex Healthcare
- Source: 5-Layer Blown Film Extrusion
- URL: https://tekni-plex.com/en/healthcare/products/5-layer-blown-film-extrusion
- Published facts:
  - five-layer coextrusion
  - ISO Class 7 cleanroom at the cited facility
  - healthcare/medical/pharmaceutical packaging applications
  - film thickness 50–200 µm
  - tube film 320–650 mm
- APS use: realistic healthcare 5-layer narrow-film archetype and evidence that cleanroom qualification belongs to a specific production capability.
- Do **not** infer: ISO Class 7 is mandatory for every healthcare blown-film product.

### SRC-OEM-RAJOO-AQUAFLEX

- Organization: Rajoo Engineers
- Source: AQUAFLEX downward blown-film line
- URL: https://rajoo.com/aquaflex.html
- Published facts:
  - downward extrusion
  - chilled-water / water-quench cooling
  - PP and PE grades; barrier polymers including PA/EVOH can be configured
- APS use: `process_route` / `cooling_route` is a hard eligibility dimension; upward air-cooled and downward water-quenched lines must not be treated as interchangeable resources.

## 4. Healthcare Resin References

### SRC-MAT-PURELL-2420F

- Manufacturer: LyondellBasell
- Grade: Purell PE 2420 F
- URL: https://www.lyondellbasell.com/en/polymers/p/Purell-PE-2420-F/0f3c5e78-3b06-4f33-993b-6144d46d32c0
- Published application: films for healthcare applications including pharmaceutical packaging.
- Typical values include MFR 0.75 g/10 min at 190 °C / 2.16 kg and density 0.923 g/cm³.

### SRC-MAT-PURELL-3020K

- Manufacturer: LyondellBasell
- Grade: Purell PE 3020K
- URL: https://www.lyondellbasell.com/en/polymers/p/Purell-PE-3020K/f782c9ba-1ad5-4608-af62-33aef4930f3b
- Published application: healthcare films including pharmaceutical packaging.
- Typical values include MFR 4 g/10 min, density 0.928 g/cm³, and published film optical/mechanical data.

### SRC-MAT-PURELL-SP170G

- Manufacturer: LyondellBasell
- Grade: Purell SP170G
- URL: https://www.lyondellbasell.com/en/polymers/p/Purell-SP170G/38b2ffd8-8447-45e3-84dd-b4c48db5c0f3
- Published application: healthcare blown film / BFS and film layers for IV-bag applications.
- Important limitation: the manufacturer explicitly requires potential pharmaceutical/medical activities to be discussed with the relevant technical/business contacts.
- APS use: manufacturer healthcare intent may support qualification workflow, but does not replace factory/end-use approval.

### SRC-MAT-BORMED-DM55PHARM

- Manufacturer: Borealis
- Grade: Bormed DM55pharm
- URL: https://www.borealisgroup.com/products/product-catalogue/bormed-dm55pharm-11
- Published facts: PP homopolymer intended for evaluation in healthcare applications; suitable for cast film and tubular water-quench blown-film extrusion; sterilisation references include EtO and steam.
- APS use: supports PP water-quench medical-film archetype.
- Important wording: `intended for evaluation` must not be converted to universal `APPROVED` automatically.

### SRC-MAT-BORMED-LE6600PH

- Manufacturer: Borealis
- Grade: Bormed LE6600-PH
- Current official medical-use statement: `Statement on Compliance to Regulations on Medical Use`, Edition 22, dated 2025-11-18.
- URL: https://www.borealisgroup.com/storage/Datasheets/bormed/le6600-ph/LE6600-PH-PL_STAT-REG_WORLD-EN-V22-PLS_PHARM-48798-10006051.pdf
- Published material references include European Pharmacopoeia monographs 3.1.3 and 3.1.4, USP `<87>`, USP `<88>` Class VI at 70 °C, USP `<661.1>`, and FDA Drug Master File DMF 027587.
- Typical material reference used by this project: LDPE, MFR 1.5 g/10 min at 190 °C / 2.16 kg, density 0.919 g/cm³.
- APS rule: this is strong manufacturer-level healthcare evidence, but still does **not** create a plant `APPROVED` qualification automatically.

### SRC-MAT-SABIC-PCGF0863

- Manufacturer: SABIC
- Grade: SABIC HDPE PCGF0863
- URL: https://www.sabic.com/en/products/polymers/polyethylene-pe/sabic-hdpe
- Published facts: healthcare HDPE, flexible packaging/pharmaceutical/device uses, density 964 kg/m³, MFR 8 g/10 min; official page references EP/USP compliance.
- APS use: healthcare HDPE candidate material only after product-specific qualification.

### Historical identity watch — Bormed LE6601-PH

The legacy project/test data may contain forms such as `Borealis_LE6601-PH`.

- `LE6601-PH` must **not** be silently renamed or aliased to `LE6600-PH`.
- The 2026-08-28 review did not confirm a current Borealis official product page for LE6601-PH.
- Historical third-party material databases still contain LE6601-PH and identify it as a historical/discontinued grade.
- APS migration action: keep the exact legacy identity, mark it unverified until an approved historical supplier/TDS/plant record is supplied, and never inherit LE6600-PH evidence by name similarity.

## 5. Barrier / Tie / PA Technical References

### SRC-MAT-EVAL-F171B

- Manufacturer: Kuraray
- Grade: EVAL F171B EVOH
- URL: https://eval.kuraray.com/en-emea/downloads/tds-eval-f171b/
- Official TDS typical values: MFR 1.6 g/10 min at 190 °C / 2.16 kg, density 1.19 g/cm³, melting temperature 183 °C, and OTR 0.3 cm³·20µm/m²·day·atm at 20 °C / 65% RH.
- Use: technical EVOH barrier reference.
- Medical status rule: `TECHNICAL_REFERENCE` unless a product-specific healthcare/regulatory qualification source is added.

### SRC-MAT-PLEXAR-PX3236

- Manufacturer: LyondellBasell
- Grade: Plexar PX3236
- URL: https://www.lyondellbasell.com/en/polymers/p/Plexar-PX3236/e105e830-491c-447f-b3c3-8babe86106ea
- Published use: tie-layer resin for bonding dissimilar materials including PA and EVOH; blown/cast film/coextrusion use.
- Typical reference: MFR 2.0 g/10 min at 190 °C / 2.16 kg and density 0.922 g/cm³.
- Medical status rule: `TECHNICAL_REFERENCE` until qualified for the target healthcare structure.

### SRC-MAT-BASF-B36L

- Manufacturer: BASF
- Grade: Ultramid B36 L
- URL: https://chemicals.basf.com/global/en/Monomers/polyamides-and-precursors
- Published use: PA6 extrusion grade for blown film, casing and water-cooled film; BASF lists melting point 220 °C.
- APS use: PA process/material capability reference.
- Medical status rule: do not infer healthcare approval from film-process suitability.
- Data rule: do not fabricate a single density/MFR value when the current official source only supports another property or a range.

## 6. Explicit Negative Control

### SRC-MAT-EXACT5101-EXCLUDE

- Manufacturer: ExxonMobil
- Grade: Exact 5101
- Product family/data source: https://www.exxonmobilchemical.com/en/chemicals/webapi/dps/v1/datasheets/150000103377/0/en
- Published blown-film use is technically suitable for packaging.
- The product datasheet legal statement explicitly states that the product is not intended for medical applications.
- APS rule: this grade is a useful negative-control test case and must be `EXCLUDED_MEDICAL` for medical-product scheduling.

## 7. Required Provenance Fields for Future Master Data

Every externally sourced or simulated capability should carry at least:

```text
source_type
source_id
source_url_or_document
source_revision_or_date
data_class               # OFFICIAL / PLANT_MASTER / ENGINEERING / LEARNED / SIMULATED
valid_from
valid_to
approved_by
confidence
notes
```

For learned rate/setup data, additionally store:

```text
sample_count
median
p10
p90
last_observed_at
model_version
```

## 8. Rules for Using Official Data in the APS Benchmark

1. OEM configurable ranges may bound simulated machines, but simulated values must remain labeled `SIMULATED_WITH_OFFICIAL_ENVELOPE`.
2. Material TDS/PDS typical values may populate material reference attributes, but are not customer specifications.
3. Healthcare-intended resin wording must not become automatic product approval.
4. Cleanroom class, cleaning cadence, purge time, setup loss and production rate are plant-specific unless the cited source explicitly defines them for the exact resource/process.
5. A plant SOP can legitimately override generic simulation values, but the source must be recorded.
6. No hard constraint may be labeled `REGULATORY` unless a cited standard/regulation actually requires that constraint for the applicable product/process.
7. Similar grade names are never identity evidence. `LE6601-PH` and `LE6600-PH` remain distinct until an authoritative source explicitly relates them.
