"""
QuickBooks payment matching — batch apply unapplied payments to invoices.

Source automation: Scripts/PaymentsMatch/202604_MatchInvoicesAndPayments.py
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_QUICKBOOKS_URL = "https://qbo.intuit.com/app/customerdetail?nameId=536"
DEFAULT_SHEET_NAME = "A R Aging Summary"

DELAY_BETWEEN_ACTIONS = 1
DELAY_SHORT = 0.3
DELAY_MICRO = 0.1

# Accept either naming convention from prepared aging exports.
CUSTOMER_COLUMNS = ("Customer", "Account")
AMOUNT_COLUMNS = ("CURRENT", "Payment")
NORMALIZED_CUSTOMER = "Customer"
NORMALIZED_AMOUNT = "CURRENT"


@dataclass
class PaymentMatchConfig:
    excel_file: str | Path
    sheet_name: str = DEFAULT_SHEET_NAME
    quickbooks_url: str = DEFAULT_QUICKBOOKS_URL
    max_customers: int = 898
    delay_between_actions: float = DELAY_BETWEEN_ACTIONS
    delay_short: float = DELAY_SHORT
    delay_micro: float = DELAY_MICRO


def _resolve_column(df: pd.DataFrame, candidates: tuple[str, ...], label: str) -> str:
    for name in candidates:
        if name in df.columns:
            return name
    options = " or ".join(repr(c) for c in candidates)
    raise ValueError(f"Sheet must include a {label} column ({options}). Found: {list(df.columns)}")


def load_payments_dataframe(config: PaymentMatchConfig) -> pd.DataFrame:
    df = pd.read_excel(config.excel_file, sheet_name=config.sheet_name)
    customer_col = _resolve_column(df, CUSTOMER_COLUMNS, "customer")
    amount_col = _resolve_column(df, AMOUNT_COLUMNS, "payment amount")
    df_payments = df[[customer_col, amount_col]].copy()
    df_payments.columns = [NORMALIZED_CUSTOMER, NORMALIZED_AMOUNT]
    df_payments = df_payments.dropna(subset=[NORMALIZED_CUSTOMER, NORMALIZED_AMOUNT])
    return df_payments[df_payments[NORMALIZED_AMOUNT] != 0]


def _wait_for_ready(prompt: str, ready_callback=None) -> None:
    if ready_callback:
        ready_callback(prompt)
        return
    input()


def search_and_select_customer(driver, wait, customer_name, config: PaymentMatchConfig) -> bool:
    print(f"\n{'=' * 60}")
    print(f"PROCESSING: {customer_name}")
    print("=" * 60)

    time.sleep(config.delay_short)

    try:
        search_box = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[data-testid="directory-search-input"]')
            )
        )
        wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'input[data-testid="directory-search-input"]')
            )
        )

        search_box.click()
        time.sleep(config.delay_micro)
        search_box.send_keys(Keys.CONTROL + "a")
        time.sleep(config.delay_micro)
        search_box.send_keys(Keys.DELETE)
        time.sleep(config.delay_short)

        search_box.send_keys(customer_name)
        time.sleep(config.delay_short)
        search_box.send_keys(Keys.RETURN)
        print(f"  ✓ Searched for: {customer_name}")
        time.sleep(config.delay_between_actions)
    except Exception as exc:
        print(f"  ✗ Search failed: {exc}")
        return False

    try:
        customer_items = driver.find_elements(
            By.CSS_SELECTOR,
            "div.DirectoryListItem__DirectoryListItemWrapper-t0tc4y-0",
        )
        print(f"  Found {len(customer_items)} search results")

        clicked = False
        backup_item = None

        for item in customer_items:
            try:
                name_element = item.find_element(
                    By.CSS_SELECTOR, "div.DirectoryListItem__NameWrapper-t0tc4y-2"
                )
                name_text = name_element.text.strip()

                item_wrapper = item.find_element(
                    By.CSS_SELECTOR, "div.DirectoryListItem__ItemWrapper-t0tc4y-1"
                )
                wrapper_class = item_wrapper.get_attribute("class")
                is_sub_account = "ibXZmr" in wrapper_class

                if name_text == customer_name:
                    if is_sub_account:
                        item.click()
                        print(f"  ✓ Clicked sub-account: {name_text}")
                        clicked = True
                        break
                    if not clicked:
                        backup_item = item
            except Exception:
                continue

        if not clicked and backup_item:
            backup_item.click()
            print(f"  ✓ Clicked parent account: {customer_name}")
            clicked = True

        if clicked:
            print("  Waiting for customer page to load...")
            try:
                wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table.sales-table"))
                )
                print("  Customer page loaded - transaction table found")
                time.sleep(config.delay_short)
            except Exception:
                print("  ⚠ Timeout waiting for transaction table, proceeding anyway...")
                time.sleep(1)
            return True

        print(f"  ✗ Could not find customer: {customer_name}")
        return False
    except Exception as exc:
        print(f"  ✗ Error selecting customer: {exc}")
        return False


def click_receive_payment_on_invoice(driver, wait, config: PaymentMatchConfig) -> bool:
    print("\n  Step 4: Looking for any Invoice with 'Receive payment' button...")

    try:
        table_rows = driver.find_elements(
            By.CSS_SELECTOR, "table.sales-table tbody tr.selectable"
        )
        print(f"  Found {len(table_rows)} transaction rows")

        for idx, row in enumerate(table_rows):
            try:
                type_cell = row.find_element(
                    By.CSS_SELECTOR, 'td[data-column-id="allsales-type"]'
                )
                transaction_type = type_cell.text.strip()

                if transaction_type != "Invoice":
                    continue

                receive_payment_buttons = row.find_elements(
                    By.XPATH,
                    './/button[.//span[contains(text(), "Receive payment")]]',
                )
                if not receive_payment_buttons:
                    continue

                receive_payment_buttons[0].click()
                print(f"  ✓ Clicked 'Receive payment' on Invoice row {idx + 1}")

                print("  Waiting for Receive Payment window to load...")
                try:
                    wait.until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//*[contains(text(), 'Receive Payment')]")
                        )
                    )
                    wait.until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//*[contains(text(), 'Outstanding Transactions')]")
                        )
                    )
                    time.sleep(config.delay_short)
                except Exception:
                    print("  ⚠ Timeout waiting for payment window, proceeding anyway...")
                    time.sleep(1)
                return True
            except Exception:
                continue

        print("  ✗ Could not find any Invoice with 'Receive payment' button")
        return False
    except Exception as exc:
        print(f"  ✗ Error finding Invoice: {exc}")
        return False


def extract_payment_date(driver, config: PaymentMatchConfig) -> str | None:
    print("\n  Step 5a: Extracting payment date from Credits section...")

    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Credits')]"))
        )
        time.sleep(config.delay_short)
    except Exception:
        print("  ⚠ Credits heading not detected, proceeding anyway...")

    date_pattern = re.compile(r"\((\d{2}/\d{2}/\d{4})\)")

    try:
        for cell in driver.find_elements(
            By.CSS_SELECTOR, "td.txp-capability-rowDescription-7u-gv"
        ):
            cell_text = cell.text
            if _is_credit_description(cell_text):
                match = date_pattern.search(cell_text)
                if match:
                    payment_date = match.group(1)
                    print(f"  ✓ Extracted payment date from first match: {payment_date}")
                    return payment_date
    except Exception:
        pass

    try:
        for link in driver.find_elements(By.CSS_SELECTOR, 'a[class*="chargesCreditsLink"]'):
            link_text = link.text
            if _is_credit_description(link_text):
                parent_cell = link.find_element(By.XPATH, "./ancestor::td")
                match = date_pattern.search(parent_cell.text)
                if match:
                    payment_date = match.group(1)
                    print(f"  ✓ Extracted payment date from first match: {payment_date}")
                    return payment_date
    except Exception:
        pass

    try:
        for cell in driver.find_elements(By.CSS_SELECTOR, 'td[role="cell"]'):
            cell_text = cell.text
            if ("Unapplied" in cell_text or "Deposit" in cell_text) and date_pattern.search(
                cell_text
            ):
                payment_date = date_pattern.search(cell_text).group(1)
                print(f"  ✓ Extracted payment date from first match: {payment_date}")
                return payment_date
    except Exception:
        pass

    print("  ✗ Could not extract date from Credits section")
    return None


def _is_credit_description(text: str) -> bool:
    lower = text.lower()
    return (
        "unapplied payment" in lower
        or "deposit" in lower
        or "Unapplied payment" in text
        or "Deposit" in text
    )


def set_payment_details_and_save(
    driver, wait, payment_date: str, config: PaymentMatchConfig
) -> bool:
    print("\n  Step 5b: Setting payment details...")

    try:
        print("  Verifying 'Deposit To' is set to 'ATB - Trust'...")
        deposit_verified = False
        for by, selector in (
            (By.CSS_SELECTOR, 'input[data-testid="account-qf__textField"]'),
            (By.CSS_SELECTOR, 'input[aria-label="Choose an account"]'),
            (By.CSS_SELECTOR, 'input[placeholder="Choose an account"]'),
        ):
            try:
                deposit_field = driver.find_element(by, selector)
                current_value = deposit_field.get_attribute("value")
                print(f"    Current Deposit To: {current_value}")

                if current_value and "ATB" in current_value and "Trust" in current_value:
                    print(f"    ✓ Deposit To is correctly set to '{current_value}'")
                    deposit_verified = True
                else:
                    print(f"    ⚠ Deposit To is '{current_value}', correcting to 'ATB - Trust'...")
                    deposit_field.click()
                    time.sleep(config.delay_micro)
                    deposit_field.send_keys(Keys.CONTROL + "a")
                    deposit_field.send_keys(Keys.DELETE)
                    time.sleep(config.delay_micro)
                    deposit_field.send_keys("ATB - Trust")
                    time.sleep(1.5)
                    deposit_field.send_keys(Keys.RETURN)
                    time.sleep(config.delay_short)
                    confirmed_value = deposit_field.get_attribute("value")
                    if confirmed_value and "ATB" in confirmed_value and "Trust" in confirmed_value:
                        print(f"    ✓ Deposit To corrected to '{confirmed_value}'")
                        deposit_verified = True
                    else:
                        print(
                            "    ✗✗✗ ERROR: Could not correct Deposit To field "
                            f"(current value: '{confirmed_value}')"
                        )
                        return False
                break
            except Exception:
                continue

        if not deposit_verified:
            print("    ⚠ Could not verify Deposit To field (may be correct by default)")

        print(f"  Setting payment date to: {payment_date}")
        date_set = False
        for by, selector in (
            (By.ID, "IDSDatePickerInput1"),
            (By.CSS_SELECTOR, 'input[placeholder="MM/DD/YYYY"]'),
        ):
            try:
                date_field = driver.find_element(by, selector)
                date_field.click()
                time.sleep(config.delay_micro)
                date_field.send_keys(Keys.CONTROL + "a")
                date_field.send_keys(Keys.DELETE)
                time.sleep(config.delay_micro)
                date_field.send_keys(payment_date)
                date_field.send_keys(Keys.TAB)
                print(f"    ✓ Payment date set to {payment_date}")
                date_set = True
                time.sleep(config.delay_short)
                break
            except Exception:
                continue

        if not date_set:
            print("    ✗ Could not find payment date field")
            return False

        print("  Verifying amount received is $0.00...")
        amount_verified = False
        for by, selector in (
            (By.ID, "sales-forms-ui/amount_received_total"),
            (By.CSS_SELECTOR, 'input[data-testid="txp-amount-field"]'),
            (By.CSS_SELECTOR, 'input[aria-label="Amount Received Total"]'),
        ):
            try:
                amount_field = driver.find_element(by, selector)
                current_value = amount_field.get_attribute("value")
                print(f"    Current amount received: {current_value}")
                if current_value not in ("$0.00", "0.00", "0", "$0", ""):
                    print(
                        f"    ✗✗✗ ERROR: Amount received is {current_value}, expected $0.00!"
                    )
                    print("    ✗✗✗ Stopping - something is wrong with this payment matching!")
                    return False
                print("    ✓ Amount received is $0.00 - correct!")
                amount_verified = True
                time.sleep(config.delay_short)
                break
            except Exception:
                continue

        if not amount_verified:
            print("    ⚠ Could not find amount received field")
            return False

        print("  Clicking 'Save and close'...")
        for by, selector in (
            (By.XPATH, '//span[text()="Save and close"]/ancestor::button'),
            (By.XPATH, '//button[contains(text(), "Save and close")]'),
        ):
            try:
                save_button = wait.until(EC.element_to_be_clickable((by, selector)))
                save_button.click()
                print("  ✓ Clicked 'Save and close'")
                try:
                    wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "table.sales-table"))
                    )
                    print("  Payment window closed - back on customer page")
                    time.sleep(1)
                except Exception:
                    print("  ⚠ Timeout waiting for return to customer page, proceeding anyway...")
                    time.sleep(2)
                return True
            except Exception:
                continue

        print("  ✗ Could not find 'Save and close' button")
        return False
    except Exception as exc:
        print(f"  ✗ Error setting payment details: {exc}")
        return False


def run_payment_match(config: PaymentMatchConfig, ready_callback=None) -> dict:
    """Run the batch. Returns summary counts."""
    print("=" * 60)
    print("LOADING EXCEL DATA")
    print("=" * 60)
    df_payments = load_payments_dataframe(config)
    batch_size = min(config.max_customers, len(df_payments))

    print(f"Total customers to process: {len(df_payments)}")
    print(f"Will process: {batch_size} customers")
    print(df_payments.head(batch_size).to_string(index=False))

    print("\n" + "=" * 60)
    print("OPENING QUICKBOOKS")
    print("=" * 60)

    edge_options = Options()
    edge_options.add_experimental_option("detach", True)
    driver = webdriver.Edge(options=edge_options)
    driver.maximize_window()
    wait = WebDriverWait(driver, 15)

    driver.get(config.quickbooks_url)
    print("\nBrowser opened. Please log in to QuickBooks.")
    print("Press Enter when ready to start processing...")
    _wait_for_ready("Press Enter when logged in and ready...", ready_callback)

    print("\n" + "=" * 60)
    print(f"STARTING BATCH PROCESSING - {batch_size} CUSTOMERS")
    print("=" * 60)

    successful = 0
    failed = 0

    for index in range(batch_size):
        customer_name = df_payments.iloc[index][NORMALIZED_CUSTOMER]
        expected_amount = df_payments.iloc[index][NORMALIZED_AMOUNT]

        print(f"\n{'#' * 60}")
        print(f"CUSTOMER {index + 1} of {batch_size}")
        print(f"Name: {customer_name}")
        print(f"Expected Payment: ${expected_amount:,.2f}")
        print(f"{'#' * 60}")

        if search_and_select_customer(driver, wait, customer_name, config):
            if click_receive_payment_on_invoice(driver, wait, config):
                payment_date = extract_payment_date(driver, config)
                if payment_date and set_payment_details_and_save(
                    driver, wait, payment_date, config
                ):
                    print(f"\n✓✓✓ Customer {index + 1} completed successfully!")
                    successful += 1
                else:
                    print(f"\n✗ Customer {index + 1} failed at save/date step")
                    failed += 1
            else:
                print(f"\n✗ Customer {index + 1} failed - could not click 'Receive payment'")
                failed += 1
        else:
            print(f"\n✗ Customer {index + 1} failed - could not find customer")
            failed += 1

    print("\n" + "=" * 60)
    print("BATCH PROCESSING COMPLETE")
    print("=" * 60)
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total: {successful + failed}")
    print("=" * 60)

    return {"successful": successful, "failed": failed, "total": successful + failed}
