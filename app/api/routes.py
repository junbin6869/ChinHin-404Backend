from fastapi import APIRouter, HTTPException, Request, Body
from app import state
import traceback
import uuid
from datetime import date, datetime
import json
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from app.services.db import db
from sqlalchemy import text

from app.schemas.copilot import CopilotRequest, CopilotResponse
from app.services.orchestrator import Orchestrator

router = APIRouter()

_orchestrator: Orchestrator | None = None


def init_orchestrator(o: Orchestrator):
    global _orchestrator
    _orchestrator = o

#step 2: user ask question
@router.post("/copilot", response_model=CopilotResponse)
def copilot(req: CopilotRequest, request: Request):
    """
    Main Copilot endpoint.

    Flow:
    1. Receive user message from frontend
    2. Pass message to orchestrator
    3. Orchestrator handles routing -> data fetch -> business agent
    4. Return final reply to frontend
    """

    try:
        # Step 1: Call orchestrator
        conv_id = req.conversation_id or str(uuid.uuid4())

        result = state.orchestrator.handle(
            user_message=req.message,
            conversation_id=conv_id,
        )
        reply = getattr(result, "reply", None)

        # Step 2: Return structured response
        return {
            "reply": reply,                 # ✅ string
            "intent": result.agent,                
            "conversation_id": conv_id,
        }   

    except ValueError as e:
        # Raised by SQL validation or JSON parsing errors
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # Catch unexpected errors (DB failure, Foundry timeout, etc.)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")
    

@router.get("/insight/promotion/active-sales")
def get_active_promotion_sales():
    """
    Return active promotion campaigns and their net sales from campaign start_date until today.
    """
    today = date.today().isoformat()

    sql = """
    SELECT
    p.promotion_id,
    p.promotion_code,
    p.name,
    COALESCE(SUM(sf.net_sales), 0) AS net_sales
    FROM dbo.promotions p
    LEFT JOIN dbo.Sales_Fact_Daily sf
    ON sf.promotion_id = p.promotion_id
    AND sf.sales_date BETWEEN p.start_date AND :today
    WHERE
    :today BETWEEN p.start_date AND p.end_date
    GROUP BY p.promotion_id, p.promotion_code, p.name
    ORDER BY net_sales DESC
    """

    db = state.orchestrator.db
    rows = db.query(sql, params={"today": today}, row_limit=200)
    for r in rows:
        r["net_sales"] = float(r["net_sales"] or 0)
    return {"items": rows}
    
@router.post("/insight/promotion/monitor")
def monitor_active_promotions(payload: dict = Body(...)):
    """
    payload expected: { "items": [ {promotion_id, promotion_code, name, net_sales}, ... ] }
    """
    items = payload.get("items") or []
    if not isinstance(items, list) or len(items) == 0:
        return {"analysis": "No active promotion data provided."}

    prompt = (
        "You are a promotion monitoring assistant.\n"
        "Given active promotion campaigns and their net_sales, identify:\n"
        "1) Which campaigns may be underperforming (relative to others)\n"
        "2) Any obvious anomalies (extremely low/zero sales)\n"
        "3) Suggested next checks (pricing, stock, channel issues, dates, mechanics)\n\n"
        "Return concise bullet points and reference the promotion_code or name.\n\n"
        f"DATA:\n{items}"
    )

    analysis = state.orchestrator.foundry.chat_once("promotion_monitor", prompt)
    return {"analysis": analysis}


# ==============================
# Procurement Insight Endpoints
# ==============================


def _safe_json_loads(raw: str) -> Dict[str, Any]:
    """Parse JSON that may be wrapped in markdown fences."""
    t = (raw or "").strip()
    if t.startswith("```"):
        t = t[t.find("{") : t.rfind("}") + 1]
    return json.loads(t)


@router.get("/insight/procurement/pending-pos")
def procurement_pending_pos():
    """List purchase requests (purchase orders with pending status)."""

    sql = """
    SELECT TOP 500
      po.po_id,
      po.supplier_id,
      po.order_date,
      po.status,
      po.total_quantity,
      STRING_AGG(CONCAT(pr.product_name, ' x ', CAST(i.ordered_quantity AS varchar(32))), ', ') 
        WITHIN GROUP (ORDER BY pr.product_name) AS items_summary
    FROM dbo.Purchase_Orders po
    LEFT JOIN dbo.PO_Items i ON i.po_id = po.po_id
    LEFT JOIN dbo.Products pr ON pr.product_id = i.product_id
    WHERE po.status = 'PENDING'
    GROUP BY po.po_id, po.supplier_id, po.order_date, po.status, po.total_quantity
    ORDER BY po.order_date DESC
    """

    rows = state.orchestrator.db.query(sql, params={})
    return {"items": rows}


@router.get("/insight/procurement/delivery-requests")
def procurement_delivery_requests():
    """List delivery requests with item summary and tracking."""

    sql = """
    SELECT TOP 500
      dr.delivery_id,
      dr.po_id,
      dr.supplier_id,
      dr.request_date,
      dr.status,
      dr.container_count,
      st.estimated_arrival,
      st.actual_arrival,
      st.delay_days,
      STRING_AGG(CONCAT(p.product_name, ' x ', CAST(di.quantity AS varchar(32))), ', ')
        WITHIN GROUP (ORDER BY p.product_name) AS items_summary
    FROM dbo.Delivery_Requests dr
    LEFT JOIN dbo.Delivery_Items di ON di.delivery_id = dr.delivery_id
    LEFT JOIN dbo.Products p ON p.product_id = di.product_id
    LEFT JOIN dbo.Shipping_Tracking st ON st.delivery_id = dr.delivery_id
    WHERE dr.status <> 'Completed'
    GROUP BY
      dr.delivery_id, dr.po_id, dr.supplier_id, dr.request_date, dr.status, dr.container_count,
      st.estimated_arrival, st.actual_arrival, st.delay_days
    ORDER BY dr.request_date DESC
    """

    rows = state.orchestrator.db.query(sql, params={})
    return {"items": rows}


def _build_in_params(ids: List[Any], prefix: str = "p") -> tuple[str, Dict[str, Any]]:
    """Build SQLAlchemy IN (:p0,:p1,...) with params dict."""
    params: Dict[str, Any] = {}
    keys: List[str] = []
    for idx, v in enumerate(ids):
        k = f"{prefix}{idx}"
        keys.append(f":{k}")
        params[k] = v
    if not keys:
        return "(NULL)", params
    return "(" + ",".join(keys) + ")", params


def _get_latest_supplier_id(product_id: Any) -> Optional[Any]:
    sql = """
    SELECT TOP 1 po.supplier_id
    FROM dbo.Purchase_Orders po
    INNER JOIN dbo.PO_Items i ON i.po_id = po.po_id
    WHERE i.product_id = :product_id AND po.supplier_id IS NOT NULL
    ORDER BY po.order_date DESC
    """
    rows = state.orchestrator.db.query(sql, params={"product_id": product_id}, row_limit=1)
    if rows:
        return rows[0].get("supplier_id")
    return None


@router.post("/insight/procurement/ai-insight/run")
def procurement_ai_insight_run(payload: dict = Body(default={})):  # noqa: B008
    """Run procurement AI insight and auto-create PO/Delivery Requests."""

    horizon_days = int(payload.get("horizon_days") or 14)
    candidate_n = int(payload.get("candidate_n") or 80)
    today = date.today().isoformat()

    # 1) Candidate products: bottom by total stock (no hardcoded threshold)
    candidates_sql = """
    SELECT TOP (@n)
      p.product_id,
      p.product_name,
      p.category,
      i.warehouse_stock,
      i.in_transit_stock,
      i.stock_in_po,
      (i.warehouse_stock + i.in_transit_stock + i.stock_in_po) AS total_stock
    FROM dbo.Products p
    INNER JOIN dbo.Inventory_Stock i ON i.product_id = p.product_id
    WHERE p.status = 'ACTIVE'
    ORDER BY total_stock ASC, p.product_name ASC
    """
    candidates = state.orchestrator.db.query(
        candidates_sql,
        params={"n": candidate_n},
        row_limit=candidate_n,
    )

    if not candidates:
        return {"analysis": "No active products found.", "created": {"purchase_orders": [], "delivery_requests": []}, "skipped": []}

    candidate_ids = [c["product_id"] for c in candidates if c.get("product_id") is not None]

    # 2) Sales history (last 6 months)
    now = datetime.now()
    start_year = now.year
    start_month = now.month - 5
    while start_month <= 0:
        start_month += 12
        start_year -= 1

    in_clause, in_params = _build_in_params(candidate_ids, prefix="pid")
    # NOTE: Sales_History.month may be stored as varchar (e.g., 'Oct').
    # Convert it to numeric month (month_num) for filtering/sorting.
    sales_sql = f"""
    SELECT TOP 500
      sh.product_id,
      sh.year,
      sh.month,
      CASE
        WHEN sh.month IN ('Jan','January') THEN 1
        WHEN sh.month IN ('Feb','February') THEN 2
        WHEN sh.month IN ('Mar','March') THEN 3
        WHEN sh.month IN ('Apr','April') THEN 4
        WHEN sh.month IN ('May') THEN 5
        WHEN sh.month IN ('Jun','June') THEN 6
        WHEN sh.month IN ('Jul','July') THEN 7
        WHEN sh.month IN ('Aug','August') THEN 8
        WHEN sh.month IN ('Sep','September') THEN 9
        WHEN sh.month IN ('Oct','October') THEN 10
        WHEN sh.month IN ('Nov','November') THEN 11
        WHEN sh.month IN ('Dec','December') THEN 12
        ELSE NULL
      END AS month_num,
      sh.quantity_sold
    FROM dbo.Sales_History sh
    WHERE sh.product_id IN {in_clause}
      AND (
        sh.year > :start_year
        OR (
          sh.year = :start_year
          AND (
            CASE
              WHEN sh.month IN ('Jan','January') THEN 1
              WHEN sh.month IN ('Feb','February') THEN 2
              WHEN sh.month IN ('Mar','March') THEN 3
              WHEN sh.month IN ('Apr','April') THEN 4
              WHEN sh.month IN ('May') THEN 5
              WHEN sh.month IN ('Jun','June') THEN 6
              WHEN sh.month IN ('Jul','July') THEN 7
              WHEN sh.month IN ('Aug','August') THEN 8
              WHEN sh.month IN ('Sep','September') THEN 9
              WHEN sh.month IN ('Oct','October') THEN 10
              WHEN sh.month IN ('Nov','November') THEN 11
              WHEN sh.month IN ('Dec','December') THEN 12
              ELSE NULL
            END
          ) >= :start_month
        )
      )
    ORDER BY
      sh.product_id,
      sh.year DESC,
      CASE
        WHEN sh.month IN ('Jan','January') THEN 1
        WHEN sh.month IN ('Feb','February') THEN 2
        WHEN sh.month IN ('Mar','March') THEN 3
        WHEN sh.month IN ('Apr','April') THEN 4
        WHEN sh.month IN ('May') THEN 5
        WHEN sh.month IN ('Jun','June') THEN 6
        WHEN sh.month IN ('Jul','July') THEN 7
        WHEN sh.month IN ('Aug','August') THEN 8
        WHEN sh.month IN ('Sep','September') THEN 9
        WHEN sh.month IN ('Oct','October') THEN 10
        WHEN sh.month IN ('Nov','November') THEN 11
        WHEN sh.month IN ('Dec','December') THEN 12
        ELSE 0
      END DESC
    """
    sales_rows = state.orchestrator.db.query(
        sales_sql,
        params={**in_params, "start_year": start_year, "start_month": start_month},
        row_limit=500,
    )

    sales_by_pid: Dict[Any, List[Dict[str, Any]]] = {}
    for r in sales_rows:
        pid = r.get("product_id")
        if pid is None:
            continue
        sales_by_pid.setdefault(pid, []).append(
            {
                "year": int(r.get("year") or 0),
                "month": int(r.get("month_num") or 0),
                "quantity_sold": float(r.get("quantity_sold") or 0),
            }
        )

    compact_payload = []
    name_map: Dict[Any, str] = {}
    for c in candidates:
        pid = c.get("product_id")
        if pid is not None:
            name_map[pid] = str(c.get("product_name") or "")
        compact_payload.append(
            {
                "product_id": pid,
                "product_name": c.get("product_name"),
                "category": c.get("category"),
                "warehouse_stock": float(c.get("warehouse_stock") or 0),
                "in_transit_stock": float(c.get("in_transit_stock") or 0),
                "stock_in_po": float(c.get("stock_in_po") or 0),
                "total_stock": float(c.get("total_stock") or 0),
                "sales_history_recent": sales_by_pid.get(pid, [])[:6],
            }
        )

    # 3) Ask forecast agent to define what is "low" and how much to add
    prompt = (
        "You are a procurement forecasting agent.\n"
        "You will receive a ranked subset of products with lowest total stock.\n"
        "Decide which products truly need replenishment and how much additional quantity to order.\n\n"
        "Return VALID JSON only in this shape:\n"
        "{\"recommendations\":[{\"product_id\":<id>,\"quantity_add\":<number>,\"reason\":\"...\"}] }\n\n"
        "Rules:\n"
        "- Do NOT invent numeric thresholds like stock < 10. Use sales trend + current stock context.\n"
        "- Keep recommendations small (max 15 items).\n"
        "- quantity_add must be > 0.\n\n"
        f"HORIZON_DAYS: {horizon_days}\n"
        f"DATA: {json.dumps(compact_payload)}"
    )

    forecast_raw = state.orchestrator.foundry.chat_once("procurement_forecasting", prompt)
    forecast_json = _safe_json_loads(forecast_raw)
    recs = forecast_json.get("recommendations") or []
    if not isinstance(recs, list):
        recs = []

    norm_recs: List[Dict[str, Any]] = []
    for r in recs[:15]:
        pid = r.get("product_id")
        qty = float(r.get("quantity_add") or 0)
        reason = str(r.get("reason") or "")
        if pid is None or qty <= 0:
            continue
        norm_recs.append({"product_id": pid, "quantity_add": qty, "reason": reason})

    if not norm_recs:
        return {
            "analysis": "No replenishment recommendations returned.",
            "forecast": forecast_json,
            "created": {"purchase_orders": [], "delivery_requests": []},
            "skipped": [],
        }

    # 4) Check open PO per product
    rec_pids = [x["product_id"] for x in norm_recs]
    rec_in, rec_params = _build_in_params(rec_pids, prefix="rp")
    open_sql = f"""
    SELECT
      x.product_id,
      x.open_remaining,
      y.latest_po_id,
      y.latest_supplier_id
    FROM (
      SELECT i.product_id, SUM(i.remaining_quantity) AS open_remaining
      FROM dbo.PO_Items i
      INNER JOIN dbo.Purchase_Orders po ON po.po_id = i.po_id
      WHERE i.product_id IN {rec_in}
        AND i.remaining_quantity > 0
        AND po.status IN ('PENDING','APPROVED','SENT')
      GROUP BY i.product_id
    ) x
    OUTER APPLY (
      SELECT TOP 1 po.po_id AS latest_po_id, po.supplier_id AS latest_supplier_id
      FROM dbo.PO_Items i2
      INNER JOIN dbo.Purchase_Orders po ON po.po_id = i2.po_id
      WHERE i2.product_id = x.product_id
        AND i2.remaining_quantity > 0
        AND po.status IN ('PENDING','APPROVED','SENT')
      ORDER BY po.order_date DESC
    ) y
    """
    open_rows = state.orchestrator.db.query(open_sql, params=rec_params, row_limit=500)
    open_map: Dict[Any, Dict[str, Any]] = {r["product_id"]: r for r in open_rows if r.get("product_id") is not None}

    created_pos: List[Dict[str, Any]] = []
    created_drs: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    engine = state.orchestrator.db.engine
    with engine.begin() as conn:
        for rec in norm_recs:
            pid = rec["product_id"]
            qty_add = float(rec["quantity_add"])
            reason = rec.get("reason") or ""

            open_info = open_map.get(pid) or {}
            open_remaining = float(open_info.get("open_remaining") or 0)
            latest_po_id = open_info.get("latest_po_id")
            latest_supplier_id = open_info.get("latest_supplier_id")

            if open_remaining > 0 and latest_po_id is not None:
                dr_qty = min(qty_add, open_remaining)

                result = conn.execute(text("""
                SELECT TOP 1 delivery_id
                FROM dbo.Delivery_Requests
                ORDER BY delivery_id DESC
                """)).scalar()

                if result:
                    num = int(result.replace("DR", ""))
                    delivery_id = f"DR{num + 1}"
                else:
                    delivery_id = "DR6001"

                # insert delivery request
                dr_insert = text("""
                INSERT INTO dbo.Delivery_Requests
                (delivery_id, po_id, supplier_id, request_date, status, container_count)
                VALUES (:delivery_id, :po_id, :supplier_id, :request_date, :status, :container_count)
                """)

                conn.execute(
                    dr_insert,
                    {
                        "delivery_id": delivery_id,
                        "po_id": latest_po_id,
                        "supplier_id": latest_supplier_id,
                        "request_date": today,
                        "status": "CREATED",
                        "container_count": 0,
                    },
                )

                conn.execute(
                    text(
                        "INSERT INTO dbo.Delivery_Items (delivery_id, product_id, quantity) "
                        "VALUES (:delivery_id, :product_id, :quantity)"
                    ),
                    {"delivery_id": delivery_id, "product_id": pid, "quantity": dr_qty},
                )

                created_drs.append(
                    {
                        "delivery_id": delivery_id,
                        "po_id": latest_po_id,
                        "supplier_id": latest_supplier_id,
                        "product_id": pid,
                        "product_name": name_map.get(pid) or "",
                        "quantity": dr_qty,
                        "reason": "Open PO exists; request supplier shipment/ETA.",
                    }
                )

                remaining_need = qty_add - dr_qty
                if remaining_need > 0:
                    supplier_id = _get_latest_supplier_id(pid)

                    po_insert = text(
                        "INSERT INTO dbo.Purchase_Orders (supplier_id, order_date, status, total_quantity) "
                        "OUTPUT INSERTED.po_id "
                        "VALUES (:supplier_id, :order_date, :status, :total_quantity)"
                    )
                    po_id = conn.execute(
                        po_insert,
                        {
                            "supplier_id": supplier_id,
                            "order_date": today,
                            "status": "PENDING",
                            "total_quantity": remaining_need,
                        },
                    ).scalar()

                    conn.execute(
                        text(
                            "INSERT INTO dbo.PO_Items (po_id, product_id, ordered_quantity, remaining_quantity) "
                            "VALUES (:po_id, :product_id, :ordered_quantity, :remaining_quantity)"
                        ),
                        {
                            "po_id": po_id,
                            "product_id": pid,
                            "ordered_quantity": remaining_need,
                            "remaining_quantity": remaining_need,
                        },
                    )

                    created_pos.append(
                        {
                            "po_id": po_id,
                            "status": "PENDING",
                            "supplier_id": supplier_id,
                            "product_id": pid,
                            "product_name": name_map.get(pid) or "",
                            "quantity": remaining_need,
                            "ai_reason": reason,
                        }
                    )

            else:
                supplier_id = _get_latest_supplier_id(pid)

                po_insert = text(
                    "INSERT INTO dbo.Purchase_Orders (supplier_id, order_date, status, total_quantity) "
                    "OUTPUT INSERTED.po_id "
                    "VALUES (:supplier_id, :order_date, :status, :total_quantity)"
                )
                po_id = conn.execute(
                    po_insert,
                    {
                        "supplier_id": supplier_id,
                        "order_date": today,
                        "status": "PENDING",
                        "total_quantity": qty_add,
                    },
                ).scalar()

                conn.execute(
                    text(
                        "INSERT INTO dbo.PO_Items (po_id, product_id, ordered_quantity, remaining_quantity) "
                        "VALUES (:po_id, :product_id, :ordered_quantity, :remaining_quantity)"
                    ),
                    {"po_id": po_id, "product_id": pid, "ordered_quantity": qty_add, "remaining_quantity": qty_add},
                )

                created_pos.append(
                    {
                        "po_id": po_id,
                        "status": "PENDING",
                        "supplier_id": supplier_id,
                        "product_id": pid,
                        "product_name": name_map.get(pid) or "",
                        "quantity": qty_add,
                        "ai_reason": reason,
                    }
                )

    return {
        "forecast": forecast_json,
        "created": {"purchase_orders": created_pos, "delivery_requests": created_drs},
        "skipped": skipped,
    }


@router.post("/approve/{po_id}")
def approve_po(po_id: str):
    if db._engine is None:
        db.init()

    try:
        sql = text("""
        UPDATE dbo.Purchase_Orders
        SET status = 'Approved'
        WHERE po_id = :po_id
        """)

        with db.engine.begin() as conn:
            result = conn.execute(sql, {"po_id": po_id})

        return {
            "message": "Approved",
            "rows": result.rowcount
        }

    except Exception as e:
        print("APPROVE PO ERROR:")
        print(e)
        traceback.print_exc()

        return {"error": str(e)}
