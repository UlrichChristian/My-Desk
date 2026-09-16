"""Financial Management blueprint — routes at /financial."""

import copy
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
    session,
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
from fin_services.account_integrations import (
    CONNECTION_TYPES,
    ROLES,
    STATUSES,
    IntegrationError,
    client_rollup,
    coverage_summary,
    create_integration,
    import_integration_sheet,
    integration_overview,
    list_vendors,
    retire_integration,
)
from fin_services.reference_data import (
    INCOME_BASES,
    INCOME_CATEGORIES,
    PRODUCT_CHANNELS,
    PRODUCT_FEE_KINDS,
    REFERENCE_STATUSES,
    ReferenceError,
    accept_parsed_products,
    list_income_accounts,
    list_products,
    review_counts,
    update_income_account,
    update_product,
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
    INTEGRATION_FILTERS,
    available_periods,
    client_period_detail,
    export_period,
    filter_by_integration,
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
                "key": "integrations",
                "name": "HRIS & Payroll Integrations",
                "icon": "fa-plug",
                "blurb": (
                    "Which clients have a payroll or HRIS feed, on which system, "
                    "and who still needs one."
                ),
                "href_name": "financial.integrations",
                "available": True,
            },
            {
                "key": "reference_review",
                "name": "Reference Review",
                "icon": "fa-tags",
                "blurb": (
                    "Classify new product codes and income accounts that "
                    "landed on import as status=review."
                ),
                "href_name": "financial.reference_review",
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
    sections = copy.deepcopy(SECTIONS)
    counts = review_counts(get_db())
    waiting = counts["total"]
    for section in sections:
        for tool in section["tools"]:
            if tool["key"] == "reference_review":
                if waiting:
                    tool["blurb"] = (
                        f"{waiting} item(s) waiting — new product codes and "
                        "income accounts from import."
                    )
                else:
                    tool["blurb"] = (
                        "Queue is clear. New product codes and income accounts "
                        "land here on the next import."
                    )
    return render_template("financial/home.html", sections=sections)


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
        "SELECT id AS import_id, created_on AS uploaded_at, period_from AS drilldown_from, "
        "period_to AS drilldown_to FROM revenue_imports "
        "WHERE status = 'loaded' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    periods = [
        row["period"]
        for row in conn.execute(
            "SELECT DISTINCT period FROM revenue_lines "
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
            "has_payroll": bool(r["Payroll"]) if "Payroll" in r.index and pd.notna(r["Payroll"]) else False,
            "has_hris": bool(r["HRIS"]) if "HRIS" in r.index and pd.notna(r["HRIS"]) else False,
            "revenue": money(r["Revenue"]),
            "premium": money(r["Premium*"], 0),
            "rev_prem": pct(r["Revenue/Premium"]),
            "lives": money(r["Lives*"], 0),
            "rev_life": money(r["Revenue/Life"]),
            "share": pct(r["Revenue Share"]),
            "revenue_raw": float(r["Revenue"]) if pd.notna(r["Revenue"]) else 0.0,
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
            corrections = [dict(r) for r in conn.execute(
                "SELECT * FROM ingest_corrections WHERE status = 'active'"
            )]
            enriched = enrich(drilldown, account_list, accounts, corrections=corrections)
            result = load_import(
                conn, enriched, accounts, account_list,
                files=saved, created_by=session.get("username"),
                metrics_mode="latest",
            )
        except Exception as exc:  # surface parse/mapping errors to the user
            flash(f"Import failed: {exc}", "error")
            return redirect(url_for("financial.biggest_clients"))

        months = len(result["periods"])
        msg = f"Imported {result['revenue_rows']:,} revenue rows across {months} month(s)."
        if result["unresolved"]:
            msg += (f" {result['unresolved']} row(s) didn't map to an account "
                    "— review recommended.")
        if result["excluded"]:
            msg += f" {result['excluded']} row(s) excluded by a correction rule."
        flash(msg, "success")
        latest = result["periods"][-1] if result["periods"] else None
        return redirect(url_for("financial.biggest_clients", period=latest))

    period = request.args.get("period") or None
    integration = request.args.get("integration") or "all"
    if integration not in INTEGRATION_FILTERS:
        integration = "all"
    query = (request.args.get("q") or "").strip()[:100]
    report = filter_by_integration(report_from_db(conn, period), integration)
    return render_template(
        "financial/biggest_clients.html",
        state=_import_state(),
        report=_fmt_report(report),
        periods=available_periods(conn),
        period=report.attrs.get("period"),
        integration=integration,
        query=query,
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
    integration = request.args.get("integration") or "all"
    if integration not in INTEGRATION_FILTERS:
        integration = "all"
    query = (request.args.get("q") or "").strip()[:100]
    periods = available_periods(conn)
    if not periods:
        flash("No data to export yet.", "error")
        return redirect(url_for("financial.biggest_clients"))
    if not period:
        period = periods[0]
    out_path = _ensure_upload_dir() / f"biggest_clients_{period}.xlsx"
    try:
        export_period(conn, out_path, period, integration=integration, query=query)
    except Exception as exc:
        flash(f"Export failed: {exc}", "error")
        return redirect(url_for(
            "financial.biggest_clients", period=period, integration=integration, q=query,
        ))
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


# ---------------------------------------------------------------------------
# HRIS / payroll integrations
# ---------------------------------------------------------------------------


@financial_bp.route("/financial/integrations")
@login_required
def integrations():
    conn = get_db()
    show = request.args.get("show", "all")
    with_integration = {"with": True, "without": False}.get(show)
    rows = integration_overview(conn, with_integration=with_integration)
    return render_template(
        "financial/integrations.html",
        rows=rows,
        summary=coverage_summary(conn),
        clients=client_rollup(conn),
        vendors=list_vendors(conn),
        show=show,
        roles=ROLES,
        statuses=STATUSES,
        connection_types=CONNECTION_TYPES,
    )


@financial_bp.route("/financial/integrations/import", methods=["POST"])
@login_required
def integrations_import():
    upload = request.files.get("sheet")
    if not upload or not upload.filename:
        flash("Choose a spreadsheet to upload.", "error")
        return redirect(url_for("financial.integrations"))

    name = secure_filename(upload.filename)
    batch_dir = _ensure_upload_dir() / f"integrations_{datetime.now():%Y%m%d_%H%M%S}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / name
    upload.save(path)

    try:
        df = (pd.read_csv(path, dtype=object) if name.lower().endswith(".csv")
              else pd.read_excel(path, dtype=object))
        result = import_integration_sheet(get_db(), df, created_by=session.get("username"))
    except (IntegrationError, ValueError) as exc:
        flash(f"Import failed: {exc}", "error")
        return redirect(url_for("financial.integrations"))

    msg = f"Imported {result['created']} integration(s)."
    if result["skipped"]:
        msg += f" {len(result['skipped'])} row(s) skipped — see the list below."
    if result["unmatched_vendors"]:
        msg += (" Unrecognised vendor(s): "
                + ", ".join(result["unmatched_vendors"])
                + " — kept as typed; add them to the catalogue if they are real.")
    flash(msg, "success" if result["created"] else "error")
    return redirect(url_for("financial.integrations"))


@financial_bp.route("/financial/integrations/add", methods=["POST"])
@login_required
def integrations_add():
    form = request.form
    try:
        create_integration(
            get_db(),
            client=(form.get("client") or "").strip(),
            vendor_name=(form.get("vendor") or "").strip(),
            role=(form.get("role") or "").strip(),
            oid=(form.get("oid") or "").strip() or None,
            connection_type=form.get("connection_type") or "manual",
            direction=form.get("direction") or "inbound",
            status=form.get("status") or "stable",
            effective_from=(form.get("effective_from") or "").strip() or None,
            external_ref=(form.get("external_ref") or "").strip() or None,
            note=(form.get("note") or "").strip() or None,
            created_by=session.get("username"),
        )
        flash("Integration added.", "success")
    except IntegrationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("financial.integrations"))


@financial_bp.route("/financial/integrations/<int:integration_id>/retire", methods=["POST"])
@login_required
def integrations_retire(integration_id: int):
    retire_integration(
        get_db(), integration_id,
        effective_to=(request.form.get("effective_to") or "").strip() or None,
        modified_by=session.get("username"),
    )
    flash("Integration closed.", "success")
    return redirect(url_for("financial.integrations"))


# ---------------------------------------------------------------------------
# Reference review — products / income accounts auto-inserted as status=review
# ---------------------------------------------------------------------------


def _review_status_filter() -> str | None:
    show = request.args.get("show", "review")
    if show == "all":
        return None
    if show in REFERENCE_STATUSES:
        return show
    return "review"


@financial_bp.route("/financial/reference-review")
@login_required
def reference_review():
    conn = get_db()
    status = _review_status_filter()
    show = request.args.get("show", "review")
    if show not in ("all",) + REFERENCE_STATUSES:
        show = "review"
    return render_template(
        "financial/reference_review.html",
        income_accounts=list_income_accounts(conn, status=status),
        products=list_products(conn, status=status),
        counts=review_counts(conn),
        show=show,
        income_categories=INCOME_CATEGORIES,
        income_bases=INCOME_BASES,
        product_channels=PRODUCT_CHANNELS,
        product_fee_kinds=PRODUCT_FEE_KINDS,
        statuses=REFERENCE_STATUSES,
    )


@financial_bp.route("/financial/reference-review/income/<int:income_id>", methods=["POST"])
@login_required
def reference_review_income(income_id: int):
    form = request.form
    try:
        update_income_account(
            get_db(),
            income_id,
            category=form.get("category") or "unclassified",
            basis=form.get("basis") or None,
            exclude_from_reports=form.get("exclude_from_reports") == "on",
            status=form.get("status") or "active",
            note=form.get("note") or None,
        )
        flash("Income account updated.", "success")
    except ReferenceError as exc:
        flash(str(exc), "error")
    show = request.form.get("show") or "review"
    return redirect(url_for("financial.reference_review", show=show))


@financial_bp.route("/financial/reference-review/products/<int:product_id>", methods=["POST"])
@login_required
def reference_review_product(product_id: int):
    form = request.form
    try:
        update_product(
            get_db(),
            product_id,
            channel=form.get("channel") or None,
            fee_kind=form.get("fee_kind") or None,
            benefit_code=form.get("benefit_code") or None,
            hst_rate=form.get("hst_rate") or None,
            status=form.get("status") or "active",
            description=form.get("description") or None,
        )
        flash("Product updated.", "success")
    except ReferenceError as exc:
        flash(str(exc), "error")
    show = request.form.get("show") or "review"
    return redirect(url_for("financial.reference_review", show=show))


@financial_bp.route("/financial/reference-review/products/accept-parsed", methods=["POST"])
@login_required
def reference_review_accept_parsed():
    n = accept_parsed_products(get_db())
    flash(
        f"Accepted {n} product code(s) as parsed (channel, benefit, HST rate kept)."
        if n else "No review products to accept.",
        "success" if n else "error",
    )
    return redirect(url_for("financial.reference_review", show="review"))
