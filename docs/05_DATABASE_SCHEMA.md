# 05 — Database Schema
## Personal Expense Tracker with Data Visualization

---

## 🗄️ Database Engine

| Property | Value |
|----------|-------|
| Engine | SQLite 3 |
| ORM | SQLAlchemy 2.x (Declarative mapping) |
| File | `data/expenses.db` |
| Connection | `sqlite:///data/expenses.db` |
| Charset | UTF-8 |

---

## 📐 ER Diagram

```
┌──────────────┐        ┌─────────────────┐
│  categories  │        │    budgets       │
│──────────────│        │─────────────────│
│ id  (PK)     │◄───┐   │ id  (PK)        │
│ name         │    │   │ category_id (FK)│──► categories.id
│ icon         │    │   │ limit_amount    │
│ color        │    │   │ month           │
└──────────────┘    │   └─────────────────┘
                    │
                    │   ┌──────────────────┐
                    │   │    expenses      │
                    │   │──────────────────│
                    └───│ id  (PK)         │
                        │ amount           │
                        │ category_id (FK) │──► categories.id
                        │ date             │
                        │ description      │
                        │ payment_method   │
                        │ created_at       │
                        │ updated_at       │
                        └──────────────────┘

┌──────────────────┐
│    incomes       │
│──────────────────│
│ id  (PK)         │
│ amount           │
│ source           │
│ date             │
│ note             │
│ created_at       │
│ updated_at       │
└──────────────────┘
```

---

## 📋 Table Definitions

---

### Table: `categories`

```sql
CREATE TABLE categories (
    id    INTEGER  PRIMARY KEY AUTOINCREMENT,
    name  TEXT     NOT NULL UNIQUE,
    icon  TEXT,                       -- emoji e.g. "🍔"
    color TEXT                        -- hex e.g. "#FF5733"
);
```

| Column | SQLAlchemy Type | Nullable | Unique | Default |
|--------|----------------|---------|--------|---------|
| `id` | `Integer` | No | Yes (PK) | autoincrement |
| `name` | `String(50)` | No | Yes | — |
| `icon` | `String(10)` | Yes | No | `NULL` |
| `color` | `String(7)` | Yes | No | `NULL` |

**Seed data (pre-populated on first run):**

| id | name | icon | color |
|----|------|------|-------|
| 1 | Food | 🍔 | #FF6B6B |
| 2 | Transport | 🚗 | #4ECDC4 |
| 3 | Shopping | 🛍️ | #45B7D1 |
| 4 | Entertainment | 🎬 | #96CEB4 |
| 5 | Healthcare | 💊 | #FFEAA7 |
| 6 | Utilities | 💡 | #DDA0DD |
| 7 | Education | 📚 | #98D8C8 |
| 8 | Other | 📦 | #B0B0B0 |

---

### Table: `expenses`

```sql
CREATE TABLE expenses (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    amount          REAL     NOT NULL CHECK(amount > 0),
    category_id     INTEGER  NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    date            TEXT     NOT NULL,     -- YYYY-MM-DD
    description     TEXT,
    payment_method  TEXT,                  -- Cash | Card | UPI | Net Banking
    created_at      TEXT     NOT NULL,     -- ISO datetime
    updated_at      TEXT
);
```

| Column | SQLAlchemy Type | Nullable | Constraint |
|--------|----------------|---------|-----------|
| `id` | `Integer` | No | PK |
| `amount` | `Float` | No | > 0 |
| `category_id` | `Integer` | No | FK → `categories.id` |
| `date` | `Date` | No | ISO 8601 |
| `description` | `String(255)` | Yes | — |
| `payment_method` | `String(50)` | Yes | — |
| `created_at` | `DateTime` | No | auto `utcnow` |
| `updated_at` | `DateTime` | Yes | auto on update |

---

### Table: `incomes`

```sql
CREATE TABLE incomes (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    amount      REAL     NOT NULL CHECK(amount > 0),
    source      TEXT     NOT NULL,     -- Salary | Freelance | Gift | etc.
    date        TEXT     NOT NULL,
    note        TEXT,
    created_at  TEXT     NOT NULL,
    updated_at  TEXT
);
```

| Column | SQLAlchemy Type | Nullable |
|--------|----------------|---------|
| `id` | `Integer` | No |
| `amount` | `Float` | No |
| `source` | `String(100)` | No |
| `date` | `Date` | No |
| `note` | `String(255)` | Yes |
| `created_at` | `DateTime` | No |
| `updated_at` | `DateTime` | Yes |

---

### Table: `budgets`

```sql
CREATE TABLE budgets (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    category_id     INTEGER  NOT NULL REFERENCES categories(id),
    limit_amount    REAL     NOT NULL CHECK(limit_amount > 0),
    month           TEXT     NOT NULL,   -- YYYY-MM  e.g. "2026-11"
    UNIQUE(category_id, month)           -- one budget per category per month
);
```

| Column | SQLAlchemy Type | Nullable | Constraint |
|--------|----------------|---------|-----------|
| `id` | `Integer` | No | PK |
| `category_id` | `Integer` | No | FK |
| `limit_amount` | `Float` | No | > 0 |
| `month` | `String(7)` | No | UNIQUE(cat, month) |

---

## 🔍 Common Queries

```sql
-- Monthly total by category
SELECT c.name, SUM(e.amount) AS total
FROM expenses e
JOIN categories c ON e.category_id = c.id
WHERE strftime('%Y-%m', e.date) = '2026-11'
GROUP BY c.name
ORDER BY total DESC;

-- Daily spending trend
SELECT e.date, SUM(e.amount) AS daily_total
FROM expenses e
WHERE strftime('%Y-%m', e.date) = '2026-11'
GROUP BY e.date
ORDER BY e.date;

-- Budget utilization
SELECT c.name, b.limit_amount,
       COALESCE(SUM(e.amount), 0) AS spent,
       ROUND(COALESCE(SUM(e.amount),0) / b.limit_amount * 100, 2) AS pct_used
FROM budgets b
JOIN categories c ON b.category_id = c.id
LEFT JOIN expenses e ON e.category_id = b.category_id
       AND strftime('%Y-%m', e.date) = b.month
WHERE b.month = '2026-11'
GROUP BY c.name;
```

---

## 🚀 Database Initialization Flow

```
App starts
  → config.DATABASE_URL is read
  → SQLAlchemy engine created: create_engine(DATABASE_URL)
  → Base.metadata.create_all(engine)   ← creates tables if not exist
  → Seed categories inserted if categories table is empty
  → Session factory created: sessionmaker(bind=engine)
```
