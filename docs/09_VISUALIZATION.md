# 09 — Visualization Reference
## Personal Expense Tracker with Data Visualization

---

## 🎨 Chart Inventory

| # | Chart Name | Type | Library | Data Source | Page |
|---|-----------|------|---------|------------|------|
| 1 | Category Spending Pie | Pie | Matplotlib | Monthly category totals | Dashboard |
| 2 | Category Bar Chart | Bar (H) | Matplotlib | Monthly category totals | Dashboard |
| 3 | Daily Spending Trend | Line | Matplotlib | Daily aggregated totals | Dashboard |
| 4 | Month-over-Month Trend | Multi-line | Plotly | 6-month category trend | Reports |
| 5 | Spending Heatmap | Heatmap | Seaborn | Month × Category pivot | Reports |
| 6 | Budget Gauge | Gauge | Plotly | Spent vs limit per category | Budget |
| 7 | Anomaly Overlay | Line+Scatter | Matplotlib | Daily totals + anomaly flags | Insights |
| 8 | Forecast Chart | Bar+Line | Plotly | Historical + forecast point | Insights |
| 9 | Income vs Expense | Grouped Bar | Matplotlib | Monthly income + expense | Dashboard |
| 10 | Payment Method Donut | Donut | Plotly | Payment method totals | Reports |

---

## 📈 Chart Specifications

---

### Chart 1: Category Spending Pie
```
Type:       matplotlib.pyplot.pie
Input:      pd.Series (index=category, values=total_amount)
Output:     plt.Figure (8×6 inches)

Styling:
  colors    = per-category color from DB (categories.color)
  autopct   = '%1.1f%%'
  shadow    = False
  startangle= 90
  explode   = top category slightly exploded (0.05)

Label format: "Food\n₹12,400"
```

---

### Chart 2: Category Bar Chart (Horizontal)
```
Type:       matplotlib.pyplot.barh
Input:      pd.Series sorted descending
Output:     plt.Figure (10×5 inches)

Styling:
  color     = gradient from #4ECDC4 → #FF6B6B
  edgecolor = 'white'
  x-axis    = amount in ₹
  y-axis    = category names
  value labels appended to right of each bar ("₹12,400")
```

---

### Chart 3: Daily Spending Trend (Line)
```
Type:       matplotlib.pyplot.plot
Input:      pd.Series (DatetimeIndex, values=daily_total)
Output:     plt.Figure (12×4 inches)

Styling:
  line      = "#2D6A4F", linewidth=2
  fill      = area under curve, alpha=0.15
  markers   = circle on each data point, size=4
  x-axis    = dates formatted as "Nov 01"
  grid      = True, linestyle='--', alpha=0.5
  annotations = anomaly days marked with red ✕
```

---

### Chart 4: Month-over-Month Multi-Line
```
Type:       plotly.graph_objects.Figure (Scatter traces)
Input:      df columns [year_month, category, total_amount]
Output:     go.Figure (interactive)

Traces:     one line per category
Hover:      "Food — Nov 2026: ₹12,400"
Legend:     visible, right side
x-axis:     month labels
y-axis:     ₹ amount
```

---

### Chart 5: Spending Heatmap
```
Type:       seaborn.heatmap
Input:      pd.DataFrame pivot (rows=month, cols=category, values=amount)
Output:     plt.Figure (12×6 inches)

Styling:
  cmap      = "YlOrRd"
  annot     = True (show ₹ values in cells)
  fmt       = ".0f"
  linewidths= 0.5
  cbar_label= "₹ Spent"
```

---

### Chart 6: Budget Gauge (Plotly)
```
Type:       plotly.graph_objects.Indicator (gauge mode)
Input:      spent: float, limit: float, category: str
Output:     go.Figure

Gauge ranges:
  0–60%   → green   #2D6A4F
  60–90%  → yellow  #F4D03F
  90–100%+ → red    #E74C3C

Needle:     points to current pct
Title:      "{category} Budget — {pct:.1f}% used"
```

---

### Chart 7: Anomaly Overlay
```
Type:       matplotlib composite
            - Line: daily totals
            - Scatter: anomaly points (red, size=80)

Anomaly markers:
  shape     = red circle with "!" annotation
  tooltip   = "Anomaly: ₹5,400 on Nov 15 (3.2× usual)"

Bands:      ±2σ shaded band to show normal range
```

---

### Chart 8: Forecast Chart
```
Type:       plotly.graph_objects (Bar + Scatter)

Bars:       historical monthly totals (grey)
Orange line:actual trend line
Red dashed: forecast point for next month

Annotation: "Forecast: ₹14,200 ± ₹1,200"
```

---

## 🔧 Rendering Pipeline

```
Service Layer returns aggregated DataFrame
        │
        ▼
ChartEngine.{method}(df) is called
        │
        ├─ Matplotlib figures → returned as plt.Figure objects
        │      └─ Streamlit: st.pyplot(fig)
        │
        └─ Plotly figures → returned as go.Figure objects
               └─ Streamlit: st.plotly_chart(fig, use_container_width=True)
```

---

## 🎨 Color Palette

| Category | Hex |
|----------|-----|
| Food | #FF6B6B |
| Transport | #4ECDC4 |
| Shopping | #45B7D1 |
| Entertainment | #96CEB4 |
| Healthcare | #FFEAA7 |
| Utilities | #DDA0DD |
| Education | #98D8C8 |
| Other | #B0B0B0 |
| Anomaly marker | #E74C3C |
| Forecast accent | #F39C12 |
| Background | #FAFAFA |
| Grid lines | #E0E0E0 |

---

## 📐 Figure Size Standards

| Use Case | Size (inches) |
|----------|--------------|
| Dashboard cards | 6×4 |
| Full-width charts | 12×5 |
| Heatmap | 12×6 |
| Gauge | 400×300 px (Plotly) |
| Forecast | 900×400 px (Plotly) |

---

## 🔡 Typography

| Element | Font | Size |
|---------|------|------|
| Chart title | Bold | 14pt |
| Axis labels | Regular | 11pt |
| Tick labels | Regular | 9pt |
| Annotations | Regular | 9pt |
| Legend | Regular | 10pt |

> All matplotlib charts use `plt.style.use('seaborn-v0_8-whitegrid')` for a clean base style.
