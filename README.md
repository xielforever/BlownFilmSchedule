# Medical PE Blown Film Machine APS Intelligent Scheduling System

[English](README.md) | [中文](README_CN.md)

![APS Dashboard Mockup](./aps_dashboard_mockup.png)

This project is an **Advanced Planning and Scheduling (APS)** system specifically developed for **medical-grade packaging materials** (such as infusion bag films, sterile instrument breathable films, etc.) using multi-layer co-extrusion blown film machines.

The system's core is built on **Google OR-Tools CP-SAT (Full Integer Constraint Programming)** solver, with **React + Vite + ECharts** on the frontend providing industrial-grade dark-theme large-screen visualization, and **FastAPI + PostgreSQL** on the backend delivering high-performance data support and parallel computation scheduling.

---

## 🌟 Core Business Challenges & Algorithm Features

Blown film machines (especially multi-layer co-extrusion types) have extremely strong continuity requirements and high changeover costs. Traditional manual scheduling often falls short. This system perfectly solves the following challenges through a digital brain:

1. **Multiple Physical Hard Constraint Filtering**:
   * Cleanroom level verification (e.g., `Class_10K` orders cannot be scheduled on `Class_100K` machines).
   * Width and thickness physical upper/lower bound matching.
   * Multi-layer co-extrusion formula (3-layer/5-layer) verification.

2. **Extreme Changeover Cost (Setup Times)**:
   * **Maximum Duration (Max)**: Multi-screw cleaning and material switching are executed in parallel, with duration depending on the slowest "pot".
   * **Cumulative Scrap Loss (Sum)**: Each cleaning event's raw material waste (Scrap) is precisely accumulated by weight.
   * **Directional Penalty**: Width change from narrow to wide is extremely fast, but wide to narrow easily causes roll collapse, resulting in directional time penalties.

3. **Compliant Maintenance Calendar Red Line**:
   * Strictly avoids fixed weekly time slots for GMP-level equipment microbial sterilization and no-load tests (e.g., no production on Sundays).
   * The algorithm has advance prediction capability, ensuring orders never cross the maintenance red line.

4. **Material Arrival Wait Time (Material Vacuum Period)**:
   * Even if a machine is idle, strict adherence to `materialAvailableMins` for safe material waiting, simulating real supply chain delays.

5. **Hierarchical Multi-Objective Solving (Lexicographical Optimization)**:
   * **Phase One**: Prioritize delivery commitments (VIP/emergency orders must never be late), calculating the minimum delay penalty score.
   * **Phase Two**: Without breaking delivery scores, aggressively compress production capacity, minimizing changeover physical time to the shortest. **This completely eradicates the problem of the algorithm blindly adjusting machines due to "high delivery penalty scores" (numerical overflow).**

---

## 📁 Directory Architecture

```text
├── api/                  # FastAPI interface definition layer (REST APIs)
│   ├── main.py           # API server entry point
│   └── routers/          # Route groups (e.g., dashboard.py, schedule.py)
├── db/                   # Database scripts
│   └── init_schema.sql   # PostgreSQL initialization DDL (15 core business tables)
├── input/                # Data input directory
│   └── 吹膜机排程数据.xlsx # Workshop master data source (machines, orders, formula tables, matrices)
├── output/               # Offline scheduling output directory (CSV, JSON, ASCII Gantt)
├── src/                  # APS core scheduling algorithm layer
│   ├── config.py         # Global configuration management
│   ├── data_ingestion.py # Pandas data cleaning, patch injection, transformation pipeline
│   ├── database.py       # DB persistence module
│   ├── models.py         # In-memory business object model definitions
│   ├── scheduler.py      # OR-Tools scheduling computation brain core class
│   └── setup_matrices.py # Changeover matrices, GMP cleaning matrix preprocessing
├── tests/                # Unit tests and boundary test scripts
├── web/                  # Frontend large-screen visualization system (React + Vite)
│   ├── src/
│   │   ├── api/          # Axios API wrappers
│   │   ├── components/   # Reusable components (Layout navigation bar, etc.)
│   │   ├── pages/        # Pages (Dashboard, GanttPage, LoginPage, etc.)
│   │   └── index.css     # Global style theme variables
├── main.py               # Local command-line scheduling engine entry point
└── generate_orders.py    # (Dev tool) Extreme boundary order stress test generator
```

---

## 🚀 Quick Start Guide

### 1. Environment Preparation
* **Python**: 3.9+
* **Node.js**: 18+
* **PostgreSQL**: 14+

Configure database connection (can be modified in `src/config.py` or use default parameters `localhost:5432`, account `postgres` / `postgres`, database name `blownfilm_aps`).

### 2. Backend Service & Database Initialization
Install Python dependencies:
```bash
pip install -r requirements.txt
```

**First Run: Initialize database structure and generate scheduling plan**
```bash
python main.py --init-db --save-db
```
*(This will automatically read Excel files from `input/`, build table structures, execute OR-Tools scheduling calculations, and finally persist to the database)*

**Start FastAPI Backend Service**
```bash
uvicorn api.main:app --reload --port 8000
```
*(API documentation: http://127.0.0.1:8000/docs)*

### 3. Start Frontend Visualization System
```bash
cd web
npm install
npm run dev
```

Open browser and visit `http://localhost:3000`.
* Default built-in demo account: `admin` / Password: `admin123`

---

## 🛠️ Testing & Advanced Usage

If you feel the initial 32 orders aren't "impressive" enough, we provide an **extreme boundary stress testing tool** that can instantly generate 200 urgent test orders conforming to machine physical upper/lower bounds:
```bash
python generate_orders.py
python main.py --save-db
```
Refresh the large-screen page to witness tens of thousands of hours of industrial-grade Gantt chart dashboards with extremely dense calculations!

### Running with Current Order Data

The scheduling entry now uses current orders, machines, formulas, and constraints from the database as the standard. Built-in demo data switching scripts are no longer provided.
After adjusting orders or machines through the Config page, you can directly use database data to generate a new active run:

```bash
python main.py --source db --save-db --triggered-by local
```

Dashboard's Run Schedule uses the same database scheduling path. Before running, please confirm that orders to be scheduled are in `PENDING` or `SCHEDULED` status, and available machines are in `ACTIVE` status.

For more complete real data scheduling checks, see `docs/real_data_scheduling.md`.

### Full Local Acceptance

Run the complete local acceptance path from the repository root:

```bash
python scripts/run_acceptance.py
```

This starts temporary FastAPI and Vite services, runs backend tests, frontend unit tests, HTTP contract tests, and Playwright workbench checks, then stops the temporary services.

---

## 📝 Contributing & License
Internally developed by the medical film packaging scheduling team. Unauthorized external open-sourcing is prohibited.
