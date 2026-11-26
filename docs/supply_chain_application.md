# Supply Chain Application (Proposed Adaptation)

> **This is a proposed design, not an implementation.** Nothing in this document was built, tested or run against real
> data, and no real company data is used or implied. It shows how the patterns already proven in this repository (raw → staging →
> validated star schema, configurable data quality rules, an auditable treatment policy, idempotent refreshes,
> reconciled KPIs) would map onto a marine-manufacturing supply chain built on an ERP/MRP system. All names, columns
> and example values are illustrative.

## 1. What carries over unchanged

| Existing component | Supply chain equivalent |
|---|---|
| `src/ingestion/socrata_client.py` (paged, retried, counted extract to an atomic file) | Paged extract from the ERP's API or a nightly database export (purchase orders, receipts, inventory snapshots) |
| `raw` schema (unchanged JSON, history kept) | Untouched copies of ERP extracts, for audit and replay |
| `staging.current_snapshot` (what the source says *now*) | The current state of open POs, which changes daily as lines are amended, received or cancelled |
| `config/validation_rules.yaml` + `src/validation/framework.py` | Rules such as "receipt quantity > ordered quantity", "promised date missing", "supplier inactive" |
| Treatment policy with `excludes_from_resolution` | "Exclude from on-time delivery (OTD) but keep in spend": the same idea of excluding a record from the affected metric only |
| `analytics` star schema + reconciled SQL/Python/DAX KPIs | Supplier scorecard: OTD, lead time, quality, backlog |
| Raw-vs-cleaned comparison | "How much do the data fixes move the supplier scorecard?" |

## 2. Entities

* **Supplier**: vendor master (ID, name, country, status, payment terms, approved/inactive).
* **Product / part master**: part number, description, unit of measure (UoM), make/buy flag, commodity, lead-time
  parameter used by MRP.
* **Purchase order (PO) header and PO line**: the line is the real unit of work (part, quantity, price, requested
  date, supplier-promised date).
* **PO line schedule**: one line can have several delivery schedules (split deliveries).
* **Goods receipt**: one row per physical receipt against a PO line (quantity received, receipt date, warehouse).
* **Quality inspection / non-conformance (NCR)**: accepted and rejected quantities per receipt, plus defect code.
* **Inventory snapshot**: on-hand, allocated and on-order quantity per part and location per day.
* **Manufacturing work order**: produces an assembly; consumes components (bill of materials).
* **MRP planned orders / exception messages**: what the planning system *wanted* to happen, for comparison
  with what did happen.

## 3. Proposed relational schema (analytics layer)

```sql
CREATE TABLE dim_supplier (
    supplier_key   SERIAL PRIMARY KEY,
    supplier_id    TEXT NOT NULL UNIQUE,          -- ERP vendor number
    supplier_name  TEXT NOT NULL,
    country        TEXT,
    status         TEXT NOT NULL CHECK (status IN ('approved','probation','inactive'))
);

CREATE TABLE dim_part (
    part_key        SERIAL PRIMARY KEY,
    part_number     TEXT NOT NULL UNIQUE,
    description     TEXT,
    uom             TEXT NOT NULL,
    commodity       TEXT,
    planned_lead_time_days INTEGER                 -- MRP parameter, compared with actual lead time
);

CREATE TABLE dim_date (date_key INTEGER PRIMARY KEY, full_date DATE NOT NULL UNIQUE /* ... as today ... */);

CREATE TABLE fact_po_line (
    po_line_id         TEXT PRIMARY KEY,           -- PO number + line number
    supplier_key       INTEGER NOT NULL REFERENCES dim_supplier,
    part_key           INTEGER NOT NULL REFERENCES dim_part,
    order_date_key     INTEGER NOT NULL REFERENCES dim_date,
    requested_date     DATE,                       -- what we asked for
    promised_date      DATE,                       -- what the supplier confirmed (may be missing)
    ordered_qty        NUMERIC(14,3) NOT NULL CHECK (ordered_qty > 0),
    received_qty       NUMERIC(14,3) NOT NULL DEFAULT 0,
    cancelled_qty      NUMERIC(14,3) NOT NULL DEFAULT 0,
    line_status        TEXT NOT NULL CHECK (line_status IN ('open','partially_received','closed','cancelled','unknown')),
    unit_price         NUMERIC(14,4),
    include_in_otd     BOOLEAN NOT NULL,           -- set by the treatment policy, like include_in_resolution_metrics
    dq_issue_count     SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE fact_goods_receipt (
    receipt_id         TEXT PRIMARY KEY,
    po_line_id         TEXT NOT NULL REFERENCES fact_po_line,
    receipt_date       DATE NOT NULL,
    received_qty       NUMERIC(14,3) NOT NULL CHECK (received_qty > 0),
    accepted_qty       NUMERIC(14,3),
    rejected_qty       NUMERIC(14,3) DEFAULT 0,
    defect_code        TEXT
);

CREATE TABLE fact_inventory_snapshot (
    snapshot_date_key  INTEGER REFERENCES dim_date,
    part_key           INTEGER REFERENCES dim_part,
    location           TEXT,
    on_hand_qty        NUMERIC(14,3),
    on_order_qty       NUMERIC(14,3),
    PRIMARY KEY (snapshot_date_key, part_key, location)
);

CREATE TABLE fact_work_order (
    work_order_id      TEXT PRIMARY KEY,
    part_key           INTEGER REFERENCES dim_part,   -- assembly produced
    planned_start      DATE, planned_finish DATE, actual_finish DATE,
    order_qty          NUMERIC(14,3), completed_qty NUMERIC(14,3),
    status             TEXT
);
```

## 4. Business rules for awkward cases

| Situation | Proposed handling | Why |
|---|---|---|
| **Partial deliveries** | OTD is measured **per receipt quantity**, not per line. A line is "fully on time" only if the cumulative received quantity reaches the ordered quantity (minus cancellations) by the promised date. Report both *line OTD* and *quantity OTD*. | A line-level yes/no hides a supplier that always ships 80% on time and the rest late. |
| **Multiple receipts per PO line** | Keep every receipt in `fact_goods_receipt`. Derive `first_receipt_date`, `completion_date` (date the cumulative quantity reached the requirement) and `received_qty` on the line. Never overwrite one receipt with the next. | Same principle as raw history in this project: keep the events, derive the state. |
| **Cancelled orders / quantities** | Exclude fully cancelled lines from OTD and lead time; keep them in a "cancellation rate" KPI. Partially cancelled lines are measured against `ordered_qty - cancelled_qty`. | Cancelled work cannot be late, but frequent cancellations are a planning signal. |
| **Missing promised date** | Do **not** treat it as on time or late. Flag it (equivalent of DQ005), exclude the line from promised-date OTD, fall back to requested-date OTD (labelled as such), and report the share of lines without a promise per supplier. | Mirrors this project's rule: a missing date excludes the record only from the metric that needs it. |
| **Receipt before order date / negative lead time** | Validity issue (like DQ006). Exclude from lead time and send for review: often a backdated PO raised after the goods arrived. | Prevents negative lead times pulling averages down. |
| **Over-receipt** (received > ordered) | Flag; keep for inventory; cap at the ordered quantity for OTD. | Tolerance is a policy setting (for example 2%) held in configuration, not code. |
| **Promised date changed many times** | Keep the history of promise changes (raw versions). Measure OTD against the *first* confirmed promise and against the *final* one, as two KPIs. | Avoids suppliers "re-promising" their way to 100% OTD. |
| **Unit-of-measure mismatch** between PO and receipt | Validation rule; convert using the part master; quarantine if no conversion exists. | Quantities otherwise reconcile wrongly. |
| **Unknown line status** | Status group `unknown`, excluded from open backlog (same as the `Unknown` status group here). | Never assume an unrecognised status means open. |

## 5. KPIs and example SQL

**Supplier on-time delivery (quantity basis, against first promised date)**

```sql
-- Quantity received on or before the promise, as a share of quantity due, per supplier and month.
-- Lines without a promised date or fully cancelled lines are excluded (counted separately).
WITH due AS (
    SELECT l.po_line_id, l.supplier_key, l.promised_date,
           l.ordered_qty - l.cancelled_qty AS qty_due
    FROM fact_po_line l
    WHERE l.include_in_otd AND l.promised_date IS NOT NULL AND l.ordered_qty > l.cancelled_qty
),
on_time AS (
    SELECT d.po_line_id,
           LEAST(d.qty_due, COALESCE(SUM(r.received_qty) FILTER (WHERE r.receipt_date <= d.promised_date), 0)) AS qty_on_time
    FROM due d LEFT JOIN fact_goods_receipt r USING (po_line_id)
    GROUP BY d.po_line_id, d.qty_due
)
SELECT s.supplier_name, date_trunc('month', d.promised_date) AS month,
       SUM(o.qty_on_time) / NULLIF(SUM(d.qty_due), 0) AS otd_qty_rate,
       COUNT(*) AS lines_due
FROM due d JOIN on_time o USING (po_line_id) JOIN dim_supplier s USING (supplier_key)
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Actual vs planned lead time (median, by supplier and part commodity)**

```sql
SELECT s.supplier_name, p.commodity,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.receipt_date - d.full_date) AS median_actual_lead_days,
       AVG(p.planned_lead_time_days) AS planned_lead_days
FROM fact_goods_receipt r
JOIN fact_po_line l USING (po_line_id)
JOIN dim_date d ON d.date_key = l.order_date_key
JOIN dim_supplier s USING (supplier_key)
JOIN dim_part p USING (part_key)
WHERE r.receipt_date >= d.full_date                -- negative lead times are a DQ issue, not data
GROUP BY 1, 2
HAVING COUNT(*) >= 10;                              -- avoid ranking on tiny samples
```

**Supplier quality (parts-per-million rejected)**

```sql
SELECT s.supplier_name,
       1e6 * SUM(r.rejected_qty) / NULLIF(SUM(r.received_qty), 0) AS reject_ppm,
       COUNT(*) FILTER (WHERE r.rejected_qty > 0) AS receipts_with_rejects
FROM fact_goods_receipt r JOIN fact_po_line l USING (po_line_id) JOIN dim_supplier s USING (supplier_key)
GROUP BY 1 ORDER BY reject_ppm DESC;
```

**Outstanding order backlog and aging (open quantity past promise)**

```sql
SELECT s.supplier_name,
       SUM(l.ordered_qty - l.cancelled_qty - l.received_qty) AS open_qty,
       COUNT(*) FILTER (WHERE l.promised_date < CURRENT_DATE) AS lines_past_due,
       MAX(CURRENT_DATE - l.promised_date) FILTER (WHERE l.promised_date < CURRENT_DATE) AS oldest_days_past_due
FROM fact_po_line l JOIN dim_supplier s USING (supplier_key)
WHERE l.line_status IN ('open', 'partially_received')
GROUP BY 1 ORDER BY lines_past_due DESC;
```

## 6. Reconciliation between systems

The same reconciliation idea as `reports/data_quality_report.md` (two independent calculations must agree before
publishing) applies across systems:

| Check | Systems | Rule |
|---|---|---|
| Received quantity on the PO line = sum of receipts | ERP purchasing vs warehouse receipts | Differences become issues with the PO line as record ID |
| Inventory movement = receipts − issues to work orders ± adjustments | Inventory snapshot vs transactions | Daily balance check per part/location |
| Supplier master consistent | ERP vs supplier portal / quality system | Inactive supplier with open POs is flagged |
| Count of open PO lines | ERP report vs analytics backlog | Must match before the scorecard is published, exactly as `total_requests` must match here |
| Planned vs actual lead time | MRP parameter vs observed medians | Parts whose actual median exceeds plan by >X% feed the continuous-improvement list |

## 7. Dashboard pages that would change

1. **Supplier scorecard**: OTD (line and quantity), median lead time vs plan, reject PPM, share of lines missing
   a promised date. Analytical targets are labelled as targets, not contractual terms, unless the contract defines them.
2. **Open order backlog**: past-due lines by supplier, part and days late (same aging buckets idea).
3. **Data quality**: missing promised dates, over-receipts, negative lead times and UoM mismatches by supplier and buyer.
4. **Impact of cleaning**: how OTD changes when the data issues are treated, which is the same raw-vs-cleaned page as today.
