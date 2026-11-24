# 📁 Project Documentation Index
## Personal Expense Tracker with Data Visualization

> **Status:** 🔵 In Planning / Pre-Build Phase
> **Last Updated:** 2026-11-23
> **Project Root:** `Personal Expense Tracker with Data Visualization/`

---

## 📋 Documentation Map

| File | Purpose | Status |
|------|---------|--------|
| [00_INDEX.md](./00_INDEX.md) | Master index (this file) | ✅ Ready |
| [01_PROJECT_OVERVIEW.md](./01_PROJECT_OVERVIEW.md) | Goals, scope, features, tech stack | ✅ Ready |
| [02_ARCHITECTURE.md](./02_ARCHITECTURE.md) | System architecture, layer diagram, component roles | ✅ Ready |
| [03_DATA_FLOW.md](./03_DATA_FLOW.md) | End-to-end data flow, pipeline stages | ✅ Ready |
| [04_MODULES.md](./04_MODULES.md) | Every module, its responsibility, inputs & outputs | ✅ Ready |
| [05_DATABASE_SCHEMA.md](./05_DATABASE_SCHEMA.md) | Tables, columns, types, constraints, ER diagram | ✅ Ready |
| [06_DATASET.md](./06_DATASET.md) | Dataset description, sources, fields, sample records | ✅ Ready |
| [07_ML_MODEL.md](./07_ML_MODEL.md) | ML model design, training pipeline, how the model learns | ✅ Ready |
| [08_API_REFERENCE.md](./08_API_REFERENCE.md) | All internal function/class APIs, signatures, examples | ✅ Ready |
| [09_VISUALIZATION.md](./09_VISUALIZATION.md) | Charts, graphs used, libraries, rendering pipeline | ✅ Ready |
| [10_CHANGELOG.md](./10_CHANGELOG.md) | Implementation log, one entry per session | ✅ Ready |

---

## 🗂️ Folder Structure (Planned)

```
Personal Expense Tracker with Data Visualization/
│
├── docs/                        ← YOU ARE HERE (all technical documentation)
│   ├── 00_INDEX.md
│   ├── 01_PROJECT_OVERVIEW.md
│   ├── 02_ARCHITECTURE.md
│   ├── 03_DATA_FLOW.md
│   ├── 04_MODULES.md
│   ├── 05_DATABASE_SCHEMA.md
│   ├── 06_DATASET.md
│   ├── 07_ML_MODEL.md
│   ├── 08_API_REFERENCE.md
│   ├── 09_VISUALIZATION.md
│   └── 10_CHANGELOG.md
│
├── src/                         ← All source code (to be built)
│   ├── main.py                  ← App entry point
│   ├── config.py                ← Centralized config & constants
│   ├── models/                  ← ML model files
│   ├── data/                    ← Data ingestion & processing
│   ├── visualization/           ← Chart generation
│   ├── ui/                      ← User interface layer
│   └── utils/                   ← Shared utilities
│
├── data/                        ← Raw and processed datasets
│   ├── raw/
│   └── processed/
│
├── notebooks/                   ← Jupyter notebooks for EDA & model training
├── tests/                       ← Unit & integration tests
├── requirements.txt             ← Python dependencies
└── README.md                    ← Public-facing README
```

---

## 🔄 How to Use This Docs Folder

1. **Before each session** — read `10_CHANGELOG.md` to see where we left off.
2. **For architecture questions** — go to `02_ARCHITECTURE.md`.
3. **For data questions** — `03_DATA_FLOW.md` + `05_DATABASE_SCHEMA.md` + `06_DATASET.md`.
4. **For ML questions** — `07_ML_MODEL.md`.
5. **For module-level questions** — `04_MODULES.md`.
6. **After each session** — a new entry is appended to `10_CHANGELOG.md`.
