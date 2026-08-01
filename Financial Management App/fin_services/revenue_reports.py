"""Biggest Clients rollup + Excel export, from an enriched frame or fin_db.

Excel export mirrors ``temp/202603_Revenue.xlsx``:
  - **Data** — Excel Table named ``Data`` (TableStyleMedium16), sample columns
  - **Revenue by Client** / **Revenue by Advisor** — native Excel PivotTables
    sourced from that Data table (built via Excel COM when available; otherwise
    formatted static summaries matching the sample layout)
"""

from __future__ import annotations

from calendar import month_name
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.worksheet.table import Table, TableStyleInfo

REPORT_COLUMNS = [
    "Client", "Advisor", "Revenue", "Premium*", "Revenue/Premium",
    "Lives*", "Revenue/Life", "Revenue Share",
]

ADVISOR_COLUMNS = [
    "Advisor", "Premium", "Revenue", "Lives",
    "Revenue/Premium", "Revenue Share", "Cumulative Share",
]

DATA_COLUMNS = [
    "Transaction date", "Transaction type", "#", "Name", "Memo/Description",
    "Full name", "Item split account", "Amount", "Balance", "Customer",
    "Product/Service", "PreCustomer", "BillingSiteExport.NAME",
    "BillingSiteExport.LEGAL NAME", "BillingSiteExport.GROUP ID",
    "BillingSiteExport.SYSTEM ID", "AccountSiteExport.oid",
    "AccountSiteExport.livesCount", "AccountSiteExport.monthlyPremium",
    "AccountSiteExport.firstBilledDate", "AccountSiteExport.lastPaAccess",
    "AccountSiteExport.consultingHouses", "AccountSiteExport.brokerList",
    "Client", "RowCount", "PremiumSplit", "LivesSplit",
]

# Non-client income buckets excluded from Biggest Clients / Change Report.
EXCLUDED_INCOME_ACCOUNTS = frozenset({
    "Referral Fees:Email Feed",
    "Statement of Work",
})

_FONT = "Lato"
_TITLE_FONT = Font(name=_FONT, size=9, bold=True)
_HEADER_FONT = Font(name=_FONT, size=9, bold=True, color="FFFFFF")
_CELL_FONT = Font(name=_FONT, size=9)
_TOTAL_FONT = Font(name=_FONT, size=9, bold=True)
_HEADER_FILL = PatternFill("solid", fgColor="5B9BD5")
_THIN = Border(
    left=Side(style="thin", color="B4B4B4"),
    right=Side(style="thin", color="B4B4B4"),
    top=Side(style="thin", color="B4B4B4"),
    bottom=Side(style="thin", color="B4B4B4"),
)


def _first_nonnull(series: pd.Series):
    s = series.dropna()
    return s.iloc[0] if len(s) else None


def _drop_excluded_income(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "income_account" not in df.columns:
        return df
    return df[~df["income_account"].isin(EXCLUDED_INCOME_ACCOUNTS)].copy()


def _rollup(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a frame with columns: client_key, advisor, amount, premium_split, lives_split."""
    df = _drop_excluded_income(df)
    if df.empty:
        out = pd.DataFrame(columns=REPORT_COLUMNS)
        out.attrs["total_revenue"] = 0.0
        return out
    grp = df.groupby("client_key", dropna=False)
    out = pd.DataFrame({
        "Client": grp.size().index,
        "Advisor": grp["advisor"].agg(_first_nonnull).values,
        "Revenue": grp["amount"].sum().values,
        "Premium*": grp["premium_split"].sum().values,
        "Lives*": grp["lives_split"].sum().values,
    })
    out["Revenue/Premium"] = out["Revenue"] / out["Premium*"].replace(0, pd.NA)
    out["Revenue/Life"] = out["Revenue"] / out["Lives*"].replace(0, pd.NA)
    total = out["Revenue"].sum()
    out["Revenue Share"] = out["Revenue"] / total if total else pd.NA
    out = out[REPORT_COLUMNS].sort_values("Revenue", ascending=False).reset_index(drop=True)
    out.attrs["total_revenue"] = float(total) if total else 0.0
    return out


def _advisor_rollup(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate by advisor — matches the sample Revenue by Advisor pivot."""
    df = _drop_excluded_income(df)
    if df.empty:
        return pd.DataFrame(columns=ADVISOR_COLUMNS)
    grp = df.groupby(df["advisor"].fillna("(blank)"), dropna=False)
    out = pd.DataFrame({
        "Advisor": grp.size().index,
        "Premium": grp["premium_split"].sum().values,
        "Revenue": grp["amount"].sum().values,
        "Lives": grp["lives_split"].sum().values,
    })
    out["Revenue/Premium"] = out["Revenue"] / out["Premium"].replace(0, pd.NA)
    total = out["Revenue"].sum()
    out["Revenue Share"] = out["Revenue"] / total if total else pd.NA
    out = out.sort_values("Revenue", ascending=False).reset_index(drop=True)
    out["Cumulative Share"] = out["Revenue Share"].cumsum()
    return out[ADVISOR_COLUMNS]


def _pick_period(available, period):
    if period:
        return period
    return sorted(p for p in available if p)[-1] if any(available) else None


def _period_title(period: str | None) -> str:
    if not period or len(period) < 7:
        return "Revenue"
    try:
        year, month = int(period[:4]), int(period[5:7])
        return f"{month_name[month]} {year} Revenue"
    except (TypeError, ValueError, IndexError):
        return f"{period} Revenue"


def biggest_clients(enriched: pd.DataFrame, period: str | None = None) -> pd.DataFrame:
    """Rank clients by revenue for a period (default: latest present) from an enriched frame."""
    period = _pick_period(enriched.get("period", pd.Series(dtype=object)).unique(), period)
    df = enriched[enriched["period"] == period] if period else enriched
    rep = _rollup(df)
    rep.attrs["period"] = period
    return rep


def available_periods(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM fact_revenue WHERE period IS NOT NULL ORDER BY period DESC"
    )]


UNMAPPED_CLIENT_LABEL = "(unmapped)"


def client_period_detail(conn, period: str, client_key: str) -> dict:
    """Income-bucket breakdown for one client in one period (Biggest Clients expand)."""
    placeholders = ",".join("?" * len(EXCLUDED_INCOME_ACCOUNTS))
    exclude = tuple(sorted(EXCLUDED_INCOME_ACCOUNTS))
    unmapped = (
        client_key is None
        or (isinstance(client_key, float) and pd.isna(client_key))
        or str(client_key).strip() == UNMAPPED_CLIENT_LABEL
    )
    display = UNMAPPED_CLIENT_LABEL if unmapped else client_key

    if unmapped:
        sql = (
            "SELECT income_account, product_code, "
            "SUM(amount) AS amount, SUM(quantity) AS quantity, "
            "SUM(lives_split) AS lives, SUM(premium_split) AS premium "
            "FROM fact_revenue "
            f"WHERE period = ? AND client_key IS NULL "
            f"AND COALESCE(income_account, '') NOT IN ({placeholders}) "
            "GROUP BY income_account, product_code "
            "ORDER BY income_account ASC, ABS(SUM(amount)) DESC"
        )
        params = (period, *exclude)
    else:
        sql = (
            "SELECT income_account, product_code, "
            "SUM(amount) AS amount, SUM(quantity) AS quantity, "
            "SUM(lives_split) AS lives, SUM(premium_split) AS premium "
            "FROM fact_revenue "
            f"WHERE period = ? AND client_key = ? "
            f"AND COALESCE(income_account, '') NOT IN ({placeholders}) "
            "GROUP BY income_account, product_code "
            "ORDER BY income_account ASC, ABS(SUM(amount)) DESC"
        )
        params = (period, client_key, *exclude)

    buckets = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        amt = float(d["amount"] or 0)
        qty = d["quantity"]
        qty_f = float(qty) if qty is not None else None
        rate = (amt / qty_f) if qty_f not in (None, 0) else None
        buckets.append({
            "income_account": d["income_account"] or "(blank)",
            "product_code": d["product_code"] or "(blank)",
            "amount": amt,
            "quantity": qty_f,
            "certs": abs(qty_f) if qty_f is not None else None,
            "rate": rate,
            "lives": float(d["lives"]) if d["lives"] is not None else None,
            "premium": float(d["premium"]) if d["premium"] is not None else None,
        })

    return {"period": period, "client": display, "buckets": buckets}


def _period_frame(conn, period: str) -> pd.DataFrame:
    placeholders = ",".join("?" * len(EXCLUDED_INCOME_ACCOUNTS))
    rows = conn.execute(
        "SELECT client_key, advisor_key AS advisor, amount, premium_split, lives_split, "
        "txn_date, txn_type, invoice_no, name_raw, memo, income_account, product_code, oid "
        f"FROM fact_revenue WHERE period = ? AND COALESCE(income_account, '') NOT IN ({placeholders})",
        (period, *sorted(EXCLUDED_INCOME_ACCOUNTS)),
    ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def report_from_db(conn, period: str | None = None) -> pd.DataFrame:
    """Build the report from fin_db for a period (default: latest)."""
    periods = available_periods(conn)
    period = _pick_period(periods, period)
    if period is None:
        empty = pd.DataFrame(columns=REPORT_COLUMNS)
        empty.attrs["period"] = None
        return empty
    df = _period_frame(conn, period)
    rep = _rollup(df)
    rep.attrs["period"] = period
    return rep


def data_from_db(conn, period: str) -> pd.DataFrame:
    """Build a sample-shaped Data sheet frame for one period."""
    df = _period_frame(conn, period)
    if df.empty:
        return pd.DataFrame(columns=DATA_COLUMNS)

    counts = df.groupby("oid")["amount"].transform("size")
    lives = df["lives_split"] * counts
    premium = df["premium_split"] * counts

    out = pd.DataFrame({
        "Transaction date": pd.to_datetime(df["txn_date"], errors="coerce"),
        "Transaction type": df["txn_type"],
        "#": df["invoice_no"],
        "Name": df["name_raw"],
        "Memo/Description": df["memo"],
        "Full name": df["income_account"],
        "Item split account": pd.NA,
        "Amount": pd.to_numeric(df["amount"], errors="coerce"),
        "Balance": pd.NA,
        "Customer": df["name_raw"],
        "Product/Service": df["product_code"],
        "PreCustomer": pd.NA,
        "BillingSiteExport.NAME": pd.NA,
        "BillingSiteExport.LEGAL NAME": pd.NA,
        "BillingSiteExport.GROUP ID": df["client_key"],
        "BillingSiteExport.SYSTEM ID": pd.NA,
        "AccountSiteExport.oid": df["oid"],
        "AccountSiteExport.livesCount": lives,
        "AccountSiteExport.monthlyPremium": premium,
        "AccountSiteExport.firstBilledDate": pd.NA,
        "AccountSiteExport.lastPaAccess": pd.NA,
        "AccountSiteExport.consultingHouses": pd.NA,
        "AccountSiteExport.brokerList": df["advisor"],
        "Client": df["client_key"],
        "RowCount": counts,
        "PremiumSplit": pd.to_numeric(df["premium_split"], errors="coerce"),
        "LivesSplit": pd.to_numeric(df["lives_split"], errors="coerce"),
    })
    return out[DATA_COLUMNS]


def _write_data_sheet(ws, data: pd.DataFrame):
    """Write the Data sheet as a formatted Excel Table named Data."""
    for r_i, row in enumerate(dataframe_to_rows(data, index=False, header=True), 1):
        for c_i, val in enumerate(row, 1):
            if val is not None and not isinstance(val, (str, bytes, bool, int)):
                try:
                    if pd.isna(val):
                        val = None
                except (TypeError, ValueError):
                    pass
            cell = ws.cell(r_i, c_i, val)
            if r_i == 1:
                cell.font = _HEADER_FONT
                cell.fill = _HEADER_FILL
            else:
                cell.font = _CELL_FONT
                header = data.columns[c_i - 1]
                if header in ("Amount", "PremiumSplit", "AccountSiteExport.monthlyPremium"):
                    cell.number_format = "#,##0.00"
                elif header in ("LivesSplit", "AccountSiteExport.livesCount", "RowCount"):
                    cell.number_format = "#,##0.00"
                elif header == "Transaction date" and val is not None:
                    cell.number_format = "YYYY-MM-DD"

    n_rows = max(len(data) + 1, 1)
    n_cols = len(data.columns)
    ref = f"A1:{get_column_letter(n_cols)}{n_rows}"
    table = Table(displayName="Data", name="Data", ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium16",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)

    widths = {
        "A": 16, "B": 13, "C": 14, "D": 28, "E": 36, "F": 34, "G": 18,
        "H": 10, "I": 10, "J": 20, "K": 16, "L": 16, "M": 28, "N": 28,
        "O": 14, "P": 16, "Q": 10, "R": 12, "S": 14, "T": 14, "U": 14,
        "V": 18, "W": 16, "X": 16, "Y": 10, "Z": 12, "AA": 10,
    }
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width


def _style_pivot_sheet(ws, title, subtitle, headers, rows, formats, widths):
    """Write a sample-like pivot summary starting at column B."""
    ws["B2"] = title
    ws["B2"].font = _TITLE_FONT
    ws["B3"] = subtitle
    ws["B3"].font = _TITLE_FONT

    ws["B5"] = "Full name"
    ws["B5"].font = _CELL_FONT
    ws["C5"] = "(All)"
    ws["C5"].font = _CELL_FONT

    header_row = 7
    for i, h in enumerate(headers):
        cell = ws.cell(header_row, 2 + i, h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = _THIN

    for r_i, row in enumerate(rows.itertuples(index=False), header_row + 1):
        for c_i, val in enumerate(row):
            cell = ws.cell(r_i, 2 + c_i, None if pd.isna(val) else val)
            cell.font = _CELL_FONT
            cell.border = _THIN
            fmt = formats.get(c_i)
            if fmt:
                cell.number_format = fmt

    total_row = header_row + 1 + len(rows)
    for c_i, col in enumerate(rows.columns):
        cell = ws.cell(total_row, 2 + c_i)
        cell.font = _TOTAL_FONT
        cell.border = _THIN
        fmt = formats.get(c_i)
        if fmt:
            cell.number_format = fmt
        if c_i == 0:
            cell.value = "Grand Total"
        elif col in ("Revenue", "Premium", "Premium*", "Lives", "Lives*"):
            cell.value = float(rows[col].sum()) if len(rows) else 0
        elif col in ("Revenue Share", "Cumulative Share"):
            cell.value = 1.0 if len(rows) else None

    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width
    ws.column_dimensions["A"].width = 3


def _build_native_pivots(path: Path, title: str) -> bool:
    """Build native Excel PivotTables on a temp copy; replace ``path`` only on success.

    Creates:
      - Revenue by Client — Client + Advisor rows; Revenue, Premium*, ratios, share
      - Revenue by Advisor — Advisor rows; Premium, Revenue, Lives, ratios, share
    Both source the ``Data`` Excel Table. Returns False if Excel/COM isn't available
    or anything fails (caller keeps the static fallback workbook).
    """
    try:
        import os
        from shutil import copy2
        from tempfile import mkstemp

        import pythoncom
        import win32com.client  # type: ignore
    except ImportError:
        return False

    xlDatabase = 1
    xlRowField = 1
    xlSum = -4157
    xlPercentOfTotal = 8
    xlTabularRow = 1

    fd, tmp = mkstemp(suffix=".xlsx")
    os.close(fd)
    tmp_path = Path(tmp)
    copy2(path, tmp_path)

    pythoncom.CoInitialize()
    excel = None
    ok = False
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AskToUpdateLinks = False
        excel.ScreenUpdating = False
        wb = excel.Workbooks.Open(str(tmp_path.resolve()))
        try:
            sheet_names = [s.Name for s in wb.Sheets]
            if "Data" not in sheet_names:
                return False

            def add_sum(pt, field, caption, num_fmt, calc=None):
                df = pt.AddDataField(pt.PivotFields(field), caption, xlSum)
                df.NumberFormat = num_fmt
                if calc is not None:
                    df.Calculation = calc
                return df

            def add_calc(pt, name, formula, caption, num_fmt):
                pt.CalculatedFields().Add(name, formula)
                df = pt.AddDataField(pt.PivotFields(name), caption, xlSum)
                df.NumberFormat = num_fmt
                return df

            def prep_sheet(name: str):
                # Clear static content; keep the sheet as a pivot host.
                ws = wb.Sheets(name)
                ws.Cells.Clear()
                ws.Range("B2").Value = title
                ws.Range("B2").Font.Bold = True
                ws.Range("B3").Value = name
                ws.Range("B3").Font.Bold = True
                ws.Range("B5").Value = "Full name"
                ws.Range("C5").Value = "(All)"
                return ws

            # --- Revenue by Client ---
            ws_c = prep_sheet("Revenue by Client")
            cache = wb.PivotCaches().Create(SourceType=xlDatabase, SourceData="Data")
            pt_c = cache.CreatePivotTable(
                TableDestination=ws_c.Range("B7"),
                TableName="PivotClient",
            )
            pt_c.PivotFields("Client").Orientation = xlRowField
            broker = pt_c.PivotFields("AccountSiteExport.brokerList")
            broker.Orientation = xlRowField
            broker.Caption = "Advisor"
            try:
                pt_c.RowAxisLayout(xlTabularRow)
                pt_c.PivotFields("Client").Subtotals = [False] * 12
                broker.Subtotals = [False] * 12
            except Exception:
                pass
            add_sum(pt_c, "Amount", "Revenue", "#,##0.00")
            add_sum(pt_c, "PremiumSplit", "Premium*", "#,##0.00")
            try:
                add_calc(pt_c, "CalcRevPrem", "=Amount/PremiumSplit", "Revenue/Premium", "0.00%")
            except Exception:
                pass
            add_sum(pt_c, "LivesSplit", "Lives*", "#,##0")
            try:
                add_calc(pt_c, "CalcRevLife", "=Amount/LivesSplit", "Revenue/Life", "#,##0.00")
            except Exception:
                pass
            add_sum(pt_c, "Amount", "Revenue Share", "0.00%", calc=xlPercentOfTotal)
            pt_c.ColumnGrand = True
            pt_c.RowGrand = True
            try:
                pt_c.PivotFields("Client").AutoSort(2, "Revenue")  # xlDescending
            except Exception:
                pass

            # --- Revenue by Advisor ---
            ws_a = prep_sheet("Revenue by Advisor")
            cache2 = wb.PivotCaches().Create(SourceType=xlDatabase, SourceData="Data")
            pt_a = cache2.CreatePivotTable(
                TableDestination=ws_a.Range("B7"),
                TableName="PivotAdvisor",
            )
            adv = pt_a.PivotFields("AccountSiteExport.brokerList")
            adv.Orientation = xlRowField
            adv.Caption = "Advisor"
            add_sum(pt_a, "PremiumSplit", "Premium", "#,##0.00")
            add_sum(pt_a, "Amount", "Revenue", "#,##0.00")
            add_sum(pt_a, "LivesSplit", "Lives", "#,##0")
            try:
                add_calc(pt_a, "CalcRevPremA", "=Amount/PremiumSplit", "Revenue/Premium", "0.00%")
            except Exception:
                pass
            add_sum(pt_a, "Amount", "Revenue Share", "0.00%", calc=xlPercentOfTotal)
            pt_a.ColumnGrand = True
            pt_a.RowGrand = True
            try:
                pt_a.PivotFields("Advisor").AutoSort(2, "Revenue")  # xlDescending
            except Exception:
                pass

            # Do not Move sheets — Excel COM Move can drop sibling sheets when
            # pivots are present. openpyxl already wrote Client, Advisor, Data order.

            final = [s.Name for s in wb.Sheets]
            if not all(n in final for n in ("Revenue by Client", "Revenue by Advisor", "Data")):
                raise RuntimeError(f"Missing sheets after pivot build: {final}")
            if wb.Sheets("Revenue by Client").PivotTables().Count < 1:
                raise RuntimeError("Client pivot missing")
            if wb.Sheets("Revenue by Advisor").PivotTables().Count < 1:
                raise RuntimeError("Advisor pivot missing")

            wb.Save()
            ok = True
        finally:
            wb.Close(SaveChanges=ok)
    except Exception:
        ok = False
    finally:
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

    if ok:
        copy2(tmp_path, path)
    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass
    return ok


def to_excel(
    report: pd.DataFrame,
    path: str | Path,
    period: str | None = None,
    data: pd.DataFrame | None = None,
    advisor_report: pd.DataFrame | None = None,
) -> Path:
    """Write Data table + Client/Advisor sheets; upgrade to native PivotTables when Excel is available."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    period = period or report.attrs.get("period")
    title = _period_title(period)
    report = report if report is not None else pd.DataFrame(columns=REPORT_COLUMNS)
    advisor_report = (
        advisor_report if advisor_report is not None
        else pd.DataFrame(columns=ADVISOR_COLUMNS)
    )
    data = data if data is not None else pd.DataFrame(columns=DATA_COLUMNS)

    wb = Workbook()

    # Static summaries first (fallback if Excel COM can't build live pivots).
    ws_client = wb.active
    ws_client.title = "Revenue by Client"
    _style_pivot_sheet(
        ws_client,
        title,
        "Revenue by Client",
        list(REPORT_COLUMNS),
        report,
        {2: "#,##0.00", 3: "#,##0.00", 4: "0.00%", 5: "#,##0", 6: "#,##0.00", 7: "0.00%"},
        {"B": 22.27, "C": 18.45, "D": 10, "E": 11, "F": 14.8, "G": 8, "H": 11, "I": 12},
    )

    ws_adv = wb.create_sheet("Revenue by Advisor")
    _style_pivot_sheet(
        ws_adv,
        title,
        "Revenue by Advisor",
        list(ADVISOR_COLUMNS),
        advisor_report,
        {1: "#,##0.00", 2: "#,##0.00", 3: "#,##0", 4: "0.00%", 5: "0.00%", 6: "0.00%"},
        {"B": 20.5, "C": 14.4, "D": 10, "E": 8, "F": 14.8, "G": 12, "H": 14},
    )

    ws_data = wb.create_sheet("Data")
    if data.empty:
        for c_i, h in enumerate(DATA_COLUMNS, 1):
            cell = ws_data.cell(1, c_i, h)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
    else:
        _write_data_sheet(ws_data, data)

    wb.save(path)

    if not data.empty:
        _build_native_pivots(path, title)

    return path


def export_period(conn, path: str | Path, period: str | None = None) -> Path:
    """Build client + advisor rollups and Data sheet for a period, then write Excel."""
    periods = available_periods(conn)
    period = _pick_period(periods, period)
    if period is None:
        raise ValueError("No revenue data to export.")
    frame = _period_frame(conn, period)
    report = _rollup(frame)
    report.attrs["period"] = period
    advisor = _advisor_rollup(frame)
    data = data_from_db(conn, period)
    return to_excel(report, path, period=period, data=data, advisor_report=advisor)
