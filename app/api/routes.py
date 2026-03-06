from fastapi import APIRouter, HTTPException, Request, Body
from app import state
import traceback
import uuid
from datetime import date, datetime
import json
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from app.services.db import db

from app.schemas.copilot import CopilotRequest, CopilotResponse
from app.services.orchestrator import Orchestrator

router = APIRouter()

_orchestrator: Orchestrator | None = None


def init_orchestrator(o: Orchestrator):
    global _orchestrator
    _orchestrator = o


@router.post("/copilot", response_model=CopilotResponse)
def copilot(req: CopilotRequest, request: Request):
    try:
        conv_id = req.conversation_id or str(uuid.uuid4())
        result = state.orchestrator.handle(
            user_message=req.message,
            conversation_id=conv_id,
        )
        reply = getattr(result, "reply", None)
        return {
            "reply": reply,
            "intent": result.agent,
            "conversation_id": conv_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")


@router.get("/insight/promotion/active-sales")
def get_active_promotion_sales():
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
    WHERE :today BETWEEN p.start_date AND p.end_date
    GROUP BY p.promotion_id, p.promotion_code, p.name
    ORDER BY net_sales DESC
    """
    rows = state.orchestrator.db.query(sql, params={"today": today}, row_limit=200)
    for r in rows:
        r["net_sales"] = float(r.get("net_sales") or 0)
    return {"items": rows}


@router.post("/insight/promotion/monitor")
def monitor_active_promotions(payload: dict = Body(...)):
    sql = """
    SELECT
        p.promotion_id,
        p.promotion_code,
        p.name AS promotion_name,
        p.start_date,
        p.end_date,
        p.promotion_type,
        p.discount_value,
        p.status,
        p.cost_of_investment,

        pr.product_id,
        pr.product_name,
        pr.category,

        SUM(COALESCE(sf.quantity_sold,0)) AS units_sold,
        SUM(COALESCE(sf.net_sales,0)) AS net_sales,
        COUNT(DISTINCT sf.sales_date) AS promo_active_days,
        COUNT(DISTINCT sf.reseller_id) AS reseller_coverage

    FROM dbo.promotions p

    LEFT JOIN dbo.Products pr
    ON pr.product_id = p.product_id

    LEFT JOIN dbo.Sales_Fact_Daily sf
    ON sf.promotion_id = p.promotion_id

    WHERE p.status = 'ACTIVE'

    GROUP BY
        p.promotion_id,
        p.promotion_code,
        p.name,
        p.start_date,
        p.end_date,
        p.promotion_type,
        p.discount_value,
        p.status,
        p.cost_of_investment,
        pr.product_id,
        pr.product_name,
        pr.category

    ORDER BY net_sales DESC
    """

    rows = state.orchestrator.db.query(sql, params={}, row_limit=200)

    items = []

    for r in rows:
        items.append({
            "promotion_id": r.get("promotion_id"),
            "promotion_code": r.get("promotion_code"),
            "promotion_name": r.get("promotion_name"),
            "product_id": r.get("product_id"),
            "product_name": r.get("product_name"),
            "category": r.get("category"),

            "start_date": str(r.get("start_date")) if r.get("start_date") is not None else None,
            "end_date": str(r.get("end_date")) if r.get("end_date") is not None else None,

            "promotion_type": r.get("promotion_type"),
            "discount_value": float(r.get("discount_value") or 0),
            "cost_of_investment": float(r.get("cost_of_investment") or 0),

            "units_sold": float(r.get("units_sold") or 0),
            "net_sales": float(r.get("net_sales") or 0),
            "promo_active_days": int(r.get("promo_active_days") or 0),
            "reseller_coverage": int(r.get("reseller_coverage") or 0),
        })

    prompt = (
        f"DATA:\n{json.dumps(items)}"
    )

    analysis = state.orchestrator.foundry.chat_once(
        "promotion_monitor",
        prompt
    )
    return {"analysis": analysis}


# ==============================
# Procurement Insight Endpoints
# ==============================


def _safe_json_loads(raw: str) -> Dict[str, Any]:
    t = (raw or "").strip()
    if t.startswith("```"):
        t = t[t.find("{") : t.rfind("}") + 1]
    return json.loads(t)


def _build_in_params(ids: List[Any], prefix: str = "p") -> tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    keys: List[str] = []
    for idx, v in enumerate(ids):
        k = f"{prefix}{idx}"
        keys.append(f":{k}")
        params[k] = v
    if not keys:
        return "(NULL)", params
    return "(" + ",".join(keys) + ")", params


def _table_has_column(table_name: str, column_name: str) -> bool:
    sql = """
    SELECT COUNT(*) AS cnt
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo'
      AND TABLE_NAME = :table_name
      AND COLUMN_NAME = :column_name
    """
    rows = state.orchestrator.db.query(
        sql,
        params={"table_name": table_name, "column_name": column_name},
        row_limit=1,
    )
    return bool(rows and int(rows[0].get("cnt") or 0) > 0)


def _po_optional_columns() -> Dict[str, bool]:
    return {
        "ai_reason": _table_has_column("Purchase_Orders", "ai_reason"),
        "snapshot_json": _table_has_column("Purchase_Orders", "snapshot_json"),
    }


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


def _next_po_id(conn) -> str:
    last_po_id = conn.execute(
        text("SELECT TOP 1 po_id FROM dbo.Purchase_Orders ORDER BY po_id DESC")
    ).scalar()

    if last_po_id:
        try:
            num = int(str(last_po_id).replace("PO", ""))
            return f"PO{num + 1}"
        except Exception:
            return f"PO{int(datetime.now().timestamp())}"
    return "PO3001"


def _get_current_pr_po_items() -> List[Dict[str, Any]]:
    has_ai_reason = _table_has_column("Purchase_Orders", "ai_reason")
    has_snapshot = _table_has_column("Purchase_Orders", "snapshot_json")
    extra_cols = []
    group_cols = []
    if has_ai_reason:
        extra_cols.append("po.ai_reason")
        group_cols.append("po.ai_reason")
    if has_snapshot:
        extra_cols.append("po.snapshot_json")
        group_cols.append("po.snapshot_json")

    extra_sql = ",\n      " + ",\n      ".join(extra_cols) if extra_cols else ""
    group_sql = ", " + ", ".join(group_cols) if group_cols else ""

    sql = f"""
    SELECT TOP 500
      po.po_id,
      po.supplier_id,
      po.order_date,
      po.status,
      po.total_quantity,
      STRING_AGG(CONCAT(pr.product_name, ' x ', CAST(i.ordered_quantity AS varchar(32))), ', ')
        WITHIN GROUP (ORDER BY pr.product_name) AS items_summary
      {extra_sql}
    FROM dbo.Purchase_Orders po
    LEFT JOIN dbo.PO_Items i ON i.po_id = po.po_id
    LEFT JOIN dbo.Products pr ON pr.product_id = i.product_id
    WHERE po.status IN ('Pending', 'Approved', 'Recommended')
    GROUP BY po.po_id, po.supplier_id, po.order_date, po.status, po.total_quantity{group_sql}
    ORDER BY
      CASE po.status WHEN 'Recommended' THEN 0 WHEN 'Pending' THEN 1 ELSE 2 END,
      po.order_date DESC
    """
    return state.orchestrator.db.query(sql, params={})

@router.get("/insight/procurement/pending-pos")
def procurement_pending_pos():
    return {"items": _get_current_pr_po_items()}


@router.get("/insight/procurement/delivery-requests")
def procurement_delivery_requests():
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


@router.post("/insight/procurement/ai-insight/run")
def procurement_ai_insight_run(payload: dict = Body(default={})):
    horizon_days = int(payload.get("horizon_days") or 14)
    candidate_n = int(payload.get("candidate_n") or 80)
    today = date.today().isoformat()
    po_optional = _po_optional_columns()

    candidates_sql = """
    WITH sales_norm AS (
        SELECT
            sh.product_id,
            sh.quantity_sold,
            sh.[year],
            CASE sh.[month]
                WHEN 'Jan' THEN 1
                WHEN 'Feb' THEN 2
                WHEN 'Mar' THEN 3
                WHEN 'Apr' THEN 4
                WHEN 'May' THEN 5
                WHEN 'Jun' THEN 6
                WHEN 'Jul' THEN 7
                WHEN 'Aug' THEN 8
                WHEN 'Sep' THEN 9
                WHEN 'Oct' THEN 10
                WHEN 'Nov' THEN 11
                WHEN 'Dec' THEN 12
                ELSE NULL
            END AS month_num
        FROM dbo.Sales_History sh
    ),
    sales_ranked AS (
        SELECT
            product_id,
            quantity_sold,
            [year],
            month_num,
            ROW_NUMBER() OVER (
                PARTITION BY product_id
                ORDER BY [year] DESC, month_num DESC
            ) AS rn
        FROM sales_norm
        WHERE month_num IS NOT NULL
    ),
    sales_agg AS (
        SELECT
            product_id,
            CAST(SUM(CASE WHEN rn <= 3 THEN quantity_sold ELSE 0 END) AS float) AS sales_last_3_months,
            CAST(AVG(CASE WHEN rn <= 3 THEN CAST(quantity_sold AS float) END) AS float) AS avg_monthly_sales
        FROM sales_ranked
        GROUP BY product_id
    )

    SELECT TOP (@n)
        p.product_id,
        p.product_name,
        p.category,

        CAST(COALESCE(i.warehouse_stock, 0) AS float) AS warehouse_stock,
        CAST(COALESCE(i.in_transit_stock, 0) AS float) AS in_transit_stock,
        CAST(COALESCE(i.stock_in_po, 0) AS float) AS stock_in_po,

        CAST(
            COALESCE(i.warehouse_stock, 0)
            + COALESCE(i.in_transit_stock, 0)
            + COALESCE(i.stock_in_po, 0)
            AS float
        ) AS available_total,

        CAST(COALESCE(sa.sales_last_3_months, 0) AS float) AS sales_last_3_months,
        CAST(COALESCE(sa.avg_monthly_sales, 0) AS float) AS avg_monthly_sales

    FROM dbo.Products p
    INNER JOIN dbo.Inventory_Stock i
        ON i.product_id = p.product_id
    LEFT JOIN sales_agg sa
        ON sa.product_id = p.product_id
    WHERE p.status = 'ACTIVE'
    ORDER BY available_total ASC, p.product_name ASC
    """
    candidates = state.orchestrator.db.query(
        candidates_sql,
        params={"n": candidate_n},
        row_limit=candidate_n,
    )

    if not candidates:
        return {
            "analysis": "No active products found.",
            "created": {"purchase_requests": [], "delivery_requests": []},
            "sufficient_products": [],
            "approval_message": "",
            "current_pr_po_count": 0,
        }

    compact_payload = []
    for c in candidates:
        compact_payload.append(
            {
                "product_id": c.get("product_id"),
                "product_name": c.get("product_name"),
                "category": c.get("category"),
                "warehouse_stock": float(c.get("warehouse_stock") or 0),
                "in_transit_stock": float(c.get("in_transit_stock") or 0),
                "sales_last_3_months": float(c.get("sales_last_3_months") or 0),
                "avg_monthly_sales": float(c.get("avg_monthly_sales") or 0),
            }
        )

    forecast_prompt = (
        "Analyze the following products using your configured forecasting and risk rules.\n"
        "Return VALID JSON only in this exact shape:\n"
        "{"
        "\"items\":["
        "{"
        "\"product_id\":\"...\","
        "\"product_name\":\"...\","
        "\"average_monthly_demand\":0,"
        "\"safety_stock\":0,"
        "\"warehouse_stock\":0,"
        "\"in_transit_stock\":0,"
        "\"total_inventory_position\":0,"
        "\"stock_coverage_months\":0,"
        "\"risk_level\":\"LOW\","
        "\"reorder_shortfall\":0,"
        "\"reason\":\"...\""
        "}"
        "]"
        "}\n\n"
        f"DATA: {json.dumps(compact_payload)}"
    )

    forecast_raw = state.orchestrator.foundry.chat_once("procurement_forecasting", forecast_prompt)
    forecast_json = _safe_json_loads(forecast_raw)
    forecast_items = forecast_json.get("items") or []

    print("FORECAST RAW:", forecast_raw)
    print("FORECAST JSON:", forecast_json)
    if not isinstance(forecast_items, list):
        forecast_items = []

    forecast_map: Dict[Any, Dict[str, Any]] = {}
    for x in forecast_items:
        pid = x.get("product_id")
        if pid is None:
            continue
        try:
            safety_stock = max(0.0, float(x.get("safety_stock") or 0))
        except Exception:
            safety_stock = 0.0
        forecast_map[pid] = {
            "safety_stock": safety_stock,
            "reason": str(x.get("reason") or ""),
        }

    created_prs: List[Dict[str, Any]] = []
    sufficient_products: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    engine = state.orchestrator.db.engine
    with engine.begin() as conn:
        for c in candidates:
            pid = c.get("product_id")
            if pid is None:
                continue

            warehouse_stock = float(c.get("warehouse_stock") or 0)
            in_transit_stock = float(c.get("in_transit_stock") or 0)
            stock_in_po = float(c.get("stock_in_po") or 0)
            available_total = float(c.get("available_total") or 0)
            safety_stock = float((forecast_map.get(pid) or {}).get("safety_stock") or 0)
            shortfall = max(0.0, safety_stock - available_total)
            forecast_reason = str((forecast_map.get(pid) or {}).get("reason") or "")

            snapshot = {
                "product_id": pid,
                "product_name": c.get("product_name"),
                "warehouse_stock": warehouse_stock,
                "in_transit_stock": in_transit_stock,
                "stock_in_po": stock_in_po,
                "available_total": available_total,
                "safety_stock": safety_stock,
                "shortfall": shortfall,
                "generated_on": today,
            }

            if shortfall <= 0:
                sufficient_products.append(
                    {
                        "product_id": pid,
                        "product_name": c.get("product_name"),
                        "available_total": available_total,
                        "safety_stock": safety_stock,
                    }
                )
                continue

            exists_sql = text(
                """
                SELECT TOP 1 po.po_id
                FROM dbo.PO_Items i
                INNER JOIN dbo.Purchase_Orders po ON po.po_id = i.po_id
                WHERE i.product_id = :product_id
                  AND po.status = 'Recommended'
                ORDER BY po.order_date DESC
                """
            )
            existing_po_id = conn.execute(exists_sql, {"product_id": pid}).scalar()
            if existing_po_id:
                skipped.append(
                    {
                        "product_id": pid,
                        "product_name": c.get("product_name"),
                        "reason": f"Open PR already exists as {existing_po_id}.",
                    }
                )
                continue

            supplier_id = _get_latest_supplier_id(pid)
            ai_reason = (
                f"Generated because available stock is {available_total:.0f}, below the forecast safety stock "
                f"of {safety_stock:.0f}. Estimated shortfall is {shortfall:.0f}."
            )
            if forecast_reason:
                ai_reason += f" Forecast note: {forecast_reason}"

            new_po_id = _next_po_id(conn)

            columns = ["po_id", "supplier_id", "order_date", "status", "total_quantity"]
            values = [":po_id", ":supplier_id", ":order_date", ":status", ":total_quantity"]
            params: Dict[str, Any] = {
                "po_id": new_po_id,
                "supplier_id": supplier_id,
                "order_date": today,
                "status": "Recommended",
                "total_quantity": shortfall,
            }
            if po_optional["ai_reason"]:
                columns.append("ai_reason")
                values.append(":ai_reason")
                params["ai_reason"] = ai_reason
            if po_optional["snapshot_json"]:
                columns.append("snapshot_json")
                values.append(":snapshot_json")
                params["snapshot_json"] = json.dumps(snapshot)

            po_insert = text(
                f"INSERT INTO dbo.Purchase_Orders ({', '.join(columns)}) OUTPUT INSERTED.po_id VALUES ({', '.join(values)})"
            )
            po_id = conn.execute(po_insert, params).scalar()

            conn.execute(
                text(
                    "INSERT INTO dbo.PO_Items (po_id, product_id, ordered_quantity, remaining_quantity) "
                    "VALUES (:po_id, :product_id, :ordered_quantity, :remaining_quantity)"
                ),
                {
                    "po_id": po_id,
                    "product_id": pid,
                    "ordered_quantity": shortfall,
                    "remaining_quantity": shortfall,
                },
            )

            created_prs.append(
                {
                    "po_id": po_id,
                    "status": "Recommended",
                    "supplier_id": supplier_id,
                    "product_id": pid,
                    "product_name": c.get("product_name") or "",
                    "requested_quantity": shortfall,
                    "quantity": shortfall,
                    "ai_reason": ai_reason,
                    "snapshot": snapshot,
                }
            )

    approval_message = ""
    try:
        current_pr_sql = """
        SELECT TOP 200
          po.po_id,
          po.supplier_id,
          po.order_date,
          po.status,
          CAST(i.ordered_quantity AS float) AS requested_quantity,
          i.product_id,
          p.product_name,
          CAST(COALESCE(s.warehouse_stock, 0) AS float) AS warehouse_stock,
          CAST(COALESCE(s.in_transit_stock, 0) AS float) AS in_transit_stock,
          CAST(COALESCE(s.stock_in_po, 0) AS float) AS stock_in_po
        FROM dbo.Purchase_Orders po
        INNER JOIN dbo.PO_Items i ON i.po_id = po.po_id
        LEFT JOIN dbo.Products p ON p.product_id = i.product_id
        LEFT JOIN dbo.Inventory_Stock s ON s.product_id = i.product_id
        WHERE po.status IN ('Recommended', 'Pending')
        ORDER BY po.order_date DESC, po.po_id DESC
        """
        current_pr_payload = state.orchestrator.db.query(current_pr_sql, params={}, row_limit=200)
        if current_pr_payload:
            approval_prompt = (
                f"CURRENT_PR_LIST: {json.dumps(current_pr_payload, default=str)}"
            )
            approval_message = state.orchestrator.foundry.chat_once(
                "procurement_approval_insight", approval_prompt
            )
    except Exception as e:
        print("APPROVAL INSIGHT ERROR:", str(e))
        traceback.print_exc()
        approval_message = ""

    refreshed = _get_current_pr_po_items()
    return {
        "forecast": forecast_json,
        "created": {
            "purchase_requests": created_prs,
            "purchase_orders": created_prs,
            "delivery_requests": [],
        },
        "current_pr_po_count": len(refreshed),
        "approval_message": approval_message,
        "sufficient_products": sufficient_products,
        "skipped": skipped,
    }


@router.post("/approve/{po_id}")
def approve_po(po_id: str):
    if db._engine is None:
        db.init()

    try:
        with db.engine.begin() as conn:
            header = conn.execute(
                text("SELECT po_id, supplier_id, status FROM dbo.Purchase_Orders WHERE po_id = :po_id"),
                {"po_id": po_id},
            ).mappings().first()
            if not header:
                raise HTTPException(status_code=404, detail=f"PO/PR {po_id} not found.")

            current_status = str(header.get("status") or "")
            if current_status not in {"Recommended", "Pending", "Approved"}:
                raise HTTPException(status_code=400, detail=f"Status {current_status} cannot be approved.")

            items = conn.execute(
                text(
                    "SELECT product_id, CAST(ordered_quantity AS float) AS ordered_quantity "
                    "FROM dbo.PO_Items WHERE po_id = :po_id"
                ),
                {"po_id": po_id},
            ).mappings().all()
            if not items:
                raise HTTPException(status_code=400, detail="This PR/PO has no PO_Items linked to it.")

            conn.execute(
                text("UPDATE dbo.Purchase_Orders SET status = 'Pending' WHERE po_id = :po_id"),
                {"po_id": po_id},
            )

            for item in items:
                conn.execute(
                    text(
                        "UPDATE dbo.Inventory_Stock "
                        "SET stock_in_po = COALESCE(stock_in_po, 0) + :qty "
                        "WHERE product_id = :product_id"
                    ),
                    {"qty": float(item.get("ordered_quantity") or 0), "product_id": item.get("product_id")},
                )

            latest_delivery = conn.execute(
                text("SELECT TOP 1 delivery_id FROM dbo.Delivery_Requests ORDER BY delivery_id DESC")
            ).scalar()
            if latest_delivery:
                try:
                    delivery_num = int(str(latest_delivery).replace("DR", "")) + 1
                    delivery_id = f"DR{delivery_num}"
                except Exception:
                    delivery_id = f"DR{int(datetime.now().timestamp())}"
            else:
                delivery_id = "DR6001"

            conn.execute(
                text(
                    "INSERT INTO dbo.Delivery_Requests "
                    "(delivery_id, po_id, supplier_id, request_date, status, container_count) "
                    "VALUES (:delivery_id, :po_id, :supplier_id, :request_date, :status, :container_count)"
                ),
                {
                    "delivery_id": delivery_id,
                    "po_id": po_id,
                    "supplier_id": header.get("supplier_id"),
                    "request_date": date.today().isoformat(),
                    "status": "CREATED",
                    "container_count": 0,
                },
            )

            for item in items:
                conn.execute(
                    text(
                        "INSERT INTO dbo.Delivery_Items (delivery_id, product_id, quantity) "
                        "VALUES (:delivery_id, :product_id, :quantity)"
                    ),
                    {
                        "delivery_id": delivery_id,
                        "product_id": item.get("product_id"),
                        "quantity": float(item.get("ordered_quantity") or 0),
                    },
                )

        return {
            "message": "Approved and converted to PO.",
            "po_id": po_id,
            "new_status": "Pending",
            "delivery_id": delivery_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
