"""Financial Management blueprint — routes at /financial."""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from fin_db.connection import get_db
from fin_services.payment_match import (
    DEFAULT_QUICKBOOKS_URL,
    DEFAULT_SHEET_NAME,
    PaymentMatchConfig,
    load_payments_dataframe,
)
from fin_services.revenue_ingest import (
    load_import,
    parse_account_list,
    parse_accounts,
    parse_drilldown,
)
from fin_services.revenue_mapping import enrich
from fin_services.revenue_change import (
    available_change_periods,
    available_revenue_periods,
    change_report as build_change_report,
    client_detail_rows,
    to_excel as change_to_excel,
)
from fin_services.revenue_reports import (
    available_periods,
    client_period_detail,
    export_period,
    report_from_db,
)
from services.auth import login_required

_APP_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = _APP_DIR / "uploads"
RUNNER_SCRIPT = _APP_DIR / "run_payment_match.py"
PULL_ACCOUNTS_RUNNER = _APP_DIR / "run_pull_accounts.py"

financial_bp = Blueprint(
    "financial",
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/financial/static",
)

SECTIONS = [
    {
        "title": "Financial Analysis",
        "blurb": "Monthly reporting from the QuickBooks general ledger. In development.",
        "tools": [
            {
                "key": "biggest_clients",
                "name": "Monthly Biggest Clients",
                "icon": "fa-ranking-star",
                "blurb": "Top clients by revenue, month by month.",
                "href_name": "financial.biggest_clients",
                "available": True,
            },
            {
                "key": "change_report",
                "name": "Monthly Change Report",
                "icon": "fa-arrow-trend-up",
                "blurb": (
                    "Revenue change by driver — new clients vs. existing-client "
                    "growth (certs, admin fees, benefits)."
                ),
                "href_name": "financial.change_report",
                "available": True,
            },
            {
                "key": "cashflow_pnl",
                "name": "Cash Flow / P&L",
                "icon": "fa-money-bill-trend-up",
                "blurb": "Profit & loss and cash-flow analysis.",
                "href_name": None,
                "available": False,
            },
        ],
    },
    {
        "title": "Tools",
        "blurb": "QuickBooks automations and one-off utilities.",
        "tools": [
            {
                "key": "payment_match",
                "name": "Match Invoices & Payments",
                "icon": "fa-hand-holding-dollar",
                "blurb": (
                    "Apply unapplied QuickBooks payments to invoices using a prepared "
                    "A/R aging export."
                ),
                "href_name": "financial.payment_match",
                "available": True,
            },
            {
                "key": "pull_accounts",
                "name": "Pull Accounts",
                "icon": "fa-cloud-arrow-down",
                "blurb": (
                    "Pull the current account list (lives, premium, advisor) from the "
                    "EA admin site into a CSV for the revenue reports."
                ),
                "href_name": "financial.pull_accounts",
                "available": True,
            },
        ],
    },
]


def _ensure_upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


@financial_bp.route("/financial")
@login_required
def home():
    return render_template("financial/home.html", sections=SECTIONS)


@financial_bp.route("/financial/payment-match", methods=["GET", "POST"])
@login_required
def payment_match():
    preview = None
    defaults = {
        "sheet_name": DEFAULT_SHEET_NAME,
        "quickbooks_url": DEFAULT_QUICKBOOKS_URL,
        "max_customers": 898,
    }

    if request.method == "POST":
        action = request.form.get("action", "launch")
        sheet_name = (request.form.get("sheet_name") or DEFAULT_SHEET_NAME).strip()
        quickbooks_url = (request.form.get("quickbooks_url") or DEFAULT_QUICKBOOKS_URL).strip()
        try:
            max_customers = max(1, int(request.form.get("max_customers") or 898))
        except ValueError:
            max_customers = 898

        upload = request.files.get("excel_file")
        if not upload or not upload.filename:
            flash("Choose an Excel file to upload.", "error")
            return redirect(url_for("financial.payment_match"))

        filename = secure_filename(upload.filename)
        if not filename.lower().endswith((".xlsx", ".xls")):
            flash("Upload must be an Excel workbook (.xlsx or .xls).", "error")
            return redirect(url_for("financial.payment_match"))

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = _ensure_upload_dir() / f"{stamp}_{uuid.uuid4().hex[:8]}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        excel_path = batch_dir / filename
        upload.save(excel_path)

        config = PaymentMatchConfig(
            excel_file=str(excel_path),
            sheet_name=sheet_name,
            quickbooks_url=quickbooks_url,
            max_customers=max_customers,
        )

        if action == "preview":
            try:
                df = load_payments_dataframe(config)
                batch_size = min(max_customers, len(df))
                preview = {
                    "total": len(df),
                    "batch_size": batch_size,
                    "rows": df.head(min(20, batch_size)).to_dict(orient="records"),
                    "filename": filename,
                }
            except Exception as exc:
                flash(f"Could not read the workbook: {exc}", "error")
                return redirect(url_for("financial.payment_match"))
            return render_template(
                "financial/payment_match.html",
                defaults={
                    "sheet_name": sheet_name,
                    "quickbooks_url": quickbooks_url,
                    "max_customers": max_customers,
                },
                preview=preview,
            )

        config_path = batch_dir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "excel_file": str(excel_path),
                    "sheet_name": sheet_name,
                    "quickbooks_url": quickbooks_url,
                    "max_customers": max_customers,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        subprocess.Popen(
            [sys.executable, str(RUNNER_SCRIPT), "--config", str(config_path)],
            cwd=str(_APP_DIR),
            creationflags=flags,
        )
        flash(
            "Payment matching launched in a new console window. Log in to QuickBooks "
            "in Edge, then press Enter in that console to start the batch.",
            "success",
        )
        return redirect(url_for("financial.payment_match"))

    return render_template(
        "financial/payment_match.html",
        defaults=defaults,
        preview=preview,
    )


# --- Financial Analysis: revenue data platform -------------------------------
# Framework skeleton (build step 1). Ingestion + report generation land in a
# later step; these routes stand up the navigable pages and upload surface.

def _import_state() -> dict:
    """Lightweight snapshot of what's in fin_db, for the page to show status."""
    conn = get_db()
    last = conn.execute(
        "SELECT import_id, uploaded_at, drilldown_from, drilldown_to "
        "FROM import_batch ORDER BY import_id DESC LIMIT 1"
    ).fetchone()
    periods = [
        row["period"]
        for row in conn.execute(
            "SELECT DISTINCT period FROM fact_revenue "
            "WHERE period IS NOT NULL ORDER BY period DESC"
        )
    ]
    return {"last_import": dict(last) if last else None, "periods": periods}


def _fmt_report(report) -> list[dict]:
    """Format the report DataFrame into display strings for the template."""

    def pct(v):
        return f"{v * 100:.2f}%" if pd.notna(v) else ""

    def money(v, dp=2):
        return f"{v:,.{dp}f}" if pd.notna(v) else ""

    rows = []
    for _, r in report.iterrows():
        rows.append({
            "client": r["Client"] if pd.notna(r["Client"]) else "(unmapped)",
            "advisor": r["Advisor"] if pd.notna(r["Advisor"]) else "",
            "revenue": money(r["Revenue"]),
            "premium": money(r["Premium*"], 0),
            "rev_prem": pct(r["Revenue/Premium"]),
            "lives": money(r["Lives*"], 0),
            "rev_life": money(r["Revenue/Life"]),
            "share": pct(r["Revenue Share"]),
        })
    return rows


@financial_bp.route("/financial/biggest-clients", methods=["GET", "POST"])
@login_required
def biggest_clients():
    conn = get_db()

    if request.method == "POST":
        files = {f: request.files.get(f) for f in ("drilldown", "account_list", "accounts_csv")}
        if not all(u and u.filename for u in files.values()):
            flash("Upload all three files: drilldown, account list, and accounts CSV.", "error")
            return redirect(url_for("financial.biggest_clients"))

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = _ensure_upload_dir() / f"revenue_{stamp}_{uuid.uuid4().hex[:8]}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        saved = {}
        for field, upload in files.items():
            name = secure_filename(upload.filename)
            upload.save(batch_dir / name)
            saved[field] = name

        try:
            drilldown = parse_drilldown(batch_dir / saved["drilldown"])
            account_list = parse_account_list(batch_dir / saved["account_list"])
            accounts = parse_accounts(batch_dir / saved["accounts_csv"])
            overrides = [dict(r) for r in conn.execute(
                "SELECT match_type, match_value, client_key FROM client_mapping_override"
            )]
            enriched = enrich(drilldown, account_list, accounts, overrides=overrides)
            result = load_import(conn, enriched, accounts, files=saved)
        except Exception as exc:  # surface parse/mapping errors to the user
            flash(f"Import failed: {exc}", "error")
            return redirect(url_for("financial.biggest_clients"))

        unresolved = int((~enriched["resolved"]).sum())
        months = len(result["periods"])
        msg = f"Imported {result['revenue_rows']:,} revenue rows across {months} month(s)."
        if unresolved:
            msg += f" {unresolved} row(s) didn't map to a client — review recommended."
        flash(msg, "success")
        latest = result["periods"][-1] if result["periods"] else None
        return redirect(url_for("financial.biggest_clients", period=latest))

    period = request.args.get("period") or None
    report = report_from_db(conn, period)
    return render_template(
        "financial/biggest_clients.html",
        state=_import_state(),
        report=_fmt_report(report),
        periods=available_periods(conn),
        period=report.attrs.get("period"),
        total_revenue=f"{report.attrs.get('total_revenue', 0):,.2f}",
        detail_url=url_for("financial.biggest_clients_detail"),
    )


@financial_bp.route("/financial/biggest-clients/detail")
@login_required
def biggest_clients_detail():
    period = request.args.get("period") or ""
    client = request.args.get("client") or ""
    if not period or not client:
        return jsonify({"error": "period and client are required"}), 400
    return jsonify(client_period_detail(get_db(), period, client))


@financial_bp.route("/financial/biggest-clients/export")
@login_required
def biggest_clients_export():
    conn = get_db()
    period = request.args.get("period") or None
    periods = available_periods(conn)
    if not periods:
        flash("No data to export yet.", "error")
        return redirect(url_for("financial.biggest_clients"))
    if not period:
        period = periods[0]
    out_path = _ensure_upload_dir() / f"biggest_clients_{period}.xlsx"
    try:
        export_period(conn, out_path, period)
    except Exception as exc:
        flash(f"Export failed: {exc}", "error")
        return redirect(url_for("financial.biggest_clients", period=period))
    return send_file(out_path, as_attachment=True, download_name=out_path.name)


def _fmt_money(v, dp=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return f"{v:,.{dp}f}"


def _fmt_change_rows(clients) -> list[dict]:
    rows = []
    for _, r in clients.iterrows():
        delta = r["Δ Revenue"]
        rows.append({
            "client": r["Client"] if pd.notna(r["Client"]) else "(unmapped)",
            "advisor": r["Advisor"] if pd.notna(r["Advisor"]) else "",
            "prior": _fmt_money(r["Prior Revenue"]),
            "current": _fmt_money(r["Current Revenue"]),
            "delta": _fmt_money(delta),
            "delta_cls": "num-pos" if delta > 0 else ("num-neg" if delta < 0 else "num"),
            "new": _fmt_money(r["New"]),
            "lost": _fmt_money(r["Lost"]),
            "certs": _fmt_money(r["Certs"]),
            "price": _fmt_money(r["Price"]),
            "benefits": _fmt_money(r["Benefits"]),
            "other": _fmt_money(r["Other"]),
            "prior_v": float(r["Prior Revenue"] or 0),
            "current_v": float(r["Current Revenue"] or 0),
            "delta_v": float(delta or 0),
            "new_v": float(r["New"] or 0),
            "lost_v": float(r["Lost"] or 0),
            "certs_v": float(r["Certs"] or 0),
            "price_v": float(r["Price"] or 0),
            "benefits_v": float(r["Benefits"] or 0),
            "other_v": float(r["Other"] or 0),
        })
    return rows


@financial_bp.route("/financial/change-report")
@login_required
def change_report():
    conn = get_db()
    periods = available_change_periods(conn)
    all_periods = available_revenue_periods(conn)
    period = request.args.get("period") or None
    prior_arg = request.args.get("prior") or None
    report = build_change_report(conn, period, prior_arg)
    summary = report["summary"]
    prior_period = report["prior_period"]
    prior_options = [p for p in all_periods if p != report["period"]]
    return render_template(
        "financial/change_report.html",
        state=_import_state(),
        periods=periods,
        prior_options=prior_options,
        period=report["period"],
        prior_period=prior_period,
        rows=_fmt_change_rows(report["clients"]),
        detail_url=url_for("financial.change_report_detail"),
        summary={
            **summary,
            "prior_revenue_fmt": _fmt_money(summary["prior_revenue"]),
            "current_revenue_fmt": _fmt_money(summary["current_revenue"]),
            "delta_fmt": _fmt_money(summary["delta"]),
            "new_fmt": _fmt_money(summary["new"]),
            "lost_fmt": _fmt_money(summary["lost"]),
            "certs_fmt": _fmt_money(summary["certs"]),
            "price_fmt": _fmt_money(summary["price"]),
            "benefits_fmt": _fmt_money(summary["benefits"]),
            "other_fmt": _fmt_money(summary["other"]),
            "residual_fmt": _fmt_money(summary["residual"]),
            "delta_cls": (
                "num-pos" if summary["delta"] > 0
                else ("num-neg" if summary["delta"] < 0 else "")
            ),
        },
    )


@financial_bp.route("/financial/change-report/detail")
@login_required
def change_report_detail():
    period = request.args.get("period") or ""
    client = request.args.get("client") or ""
    prior = request.args.get("prior") or None
    if not period or not client:
        return jsonify({"error": "period and client are required"}), 400
    detail = client_detail_rows(get_db(), period, client, prior)
    if detail["prior_period"] is None:
        return jsonify({"error": "invalid period"}), 400
    return jsonify(detail)


@financial_bp.route("/financial/change-report/export")
@login_required
def change_report_export():
    conn = get_db()
    periods = available_change_periods(conn)
    if not periods:
        flash("No data to export yet — import revenue on Biggest Clients first.", "error")
        return redirect(url_for("financial.change_report"))
    period = request.args.get("period") or periods[0]
    prior_arg = request.args.get("prior") or None
    report = build_change_report(conn, period, prior_arg)
    period = report["period"]
    prior_period = report["prior_period"]
    out_path = _ensure_upload_dir() / f"change_report_{period}_vs_{prior_period}.xlsx"
    try:
        change_to_excel(report, out_path)
    except Exception as exc:
        flash(f"Export failed: {exc}", "error")
        return redirect(url_for(
            "financial.change_report", period=period, prior=prior_period,
        ))
    return send_file(out_path, as_attachment=True, download_name=out_path.name)


@financial_bp.route("/financial/pull-accounts", methods=["GET", "POST"])
@login_required
def pull_accounts():
    if request.method == "POST":
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = _ensure_upload_dir() / f"accounts_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_csv = out_dir / "ea_accounts.csv"

        config_path = out_dir / "config.json"
        config_path.write_text(
            json.dumps({"output_csv": str(output_csv)}, indent=2),
            encoding="utf-8",
        )

        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        subprocess.Popen(
            [sys.executable, str(PULL_ACCOUNTS_RUNNER), "--config", str(config_path)],
            cwd=str(_APP_DIR),
            creationflags=flags,
        )
        flash(
            "Accounts pull launched in a new console window. Log in to the EA admin site "
            "in Edge, make sure the accounts grid is showing, then press Enter in that "
            f"console. The CSV will be saved to {output_csv}.",
            "success",
        )
        return redirect(url_for("financial.pull_accounts"))

    return render_template("financial/pull_accounts.html")
