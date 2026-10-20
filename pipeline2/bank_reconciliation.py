"""Decimal statement arithmetic and conservative payslip-to-bank matching."""

from __future__ import annotations

import calendar
import re
from datetime import date as Date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field

TOLERANCE = Decimal("1")


class Transaction(BaseModel):
    transaction_id: str
    date: Date | None = None
    description: str = ""
    debit: Decimal | None = None
    credit: Decimal | None = None
    balance: Decimal | None = None
    page: int = Field(default=1, ge=1, le=8)
    row: int = Field(ge=1)


def money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in {"null", "n/a", "-", "—", "unreadable"}:
        return None
    raw = re.sub(r"^(?:Rs\.?|INR|₹)\s*", "", raw, flags=re.I).replace(",", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    try:
        result = Decimal(raw)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def iso_date(value: Any) -> Date | None:
    try:
        return Date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def normalize_statement(fields: dict) -> tuple[dict, list[str]]:
    """Retain every row, including invalid ones; never silently drop a row."""
    result = dict(fields)
    warnings = []
    transactions = fields.get("transactions")
    if not isinstance(transactions, list):
        transactions = []
        warnings.append("No readable transaction table was extracted.")
    rows = []
    for index, item in enumerate(transactions):
        row = item if isinstance(item, dict) else {}
        debit, credit = money(row.get("debit")), money(row.get("credit"))
        # A blank opposite column on a readable one-sided transaction is zero.
        if debit is not None and credit is None and row.get("credit") in (None, "", "-", "—"):
            credit = Decimal(0)
        if credit is not None and debit is None and row.get("debit") in (None, "", "-", "—"):
            debit = Decimal(0)
        valid = debit is not None and credit is not None and debit >= 0 and credit >= 0 and not (debit > 0 and credit > 0)
        try:
            normalized = Transaction(transaction_id=f"txn_{index + 1}", date=iso_date(row.get("date")),
                description=str(row.get("description") or ""), debit=debit, credit=credit,
                balance=money(row.get("balance")), page=row.get("page") or 1, row=index + 1)
        except Exception:
            valid = False
            normalized = Transaction(transaction_id=f"txn_{index + 1}", row=index + 1)
        data = normalized.model_dump(mode="json")
        data["valid"] = valid
        rows.append(data)
        if not valid:
            warnings.append(f"Transaction row {index + 1} is unreadable or has ambiguous debit/credit values.")
    for field in ["opening_balance", "closing_balance"]:
        value = money(fields.get(field))
        result[field] = str(value) if value is not None else None
    result["transactions"] = rows
    result["transactions_complete"] = fields.get("transactions_complete") is True and bool(rows) and not warnings
    result["currency"] = str(fields.get("currency") or "INR").upper()
    return result, warnings


def _check(code: str, detail: str, passed: bool | None, observed=None, expected=None, **extra) -> dict:
    return {"check": code, "field": "transactions", "passed": passed,
            "severity": "high" if passed is False else "info", "detail": detail,
            "document_value": str(observed) if observed is not None else None,
            "expected": str(expected) if expected is not None else None,
            "source": "deterministic_validator", **extra}


def statement_checks(fields: dict) -> list[dict]:
    fields, warnings = normalize_statement(fields)
    rows = fields["transactions"]
    if fields["currency"] != "INR" or not rows:
        return [_check("statement_totals", "No supported INR transaction table is available.", None)]
    dates = [iso_date(row["date"]) for row in rows]
    if any(d is None for d in dates):
        return [_check("statement_totals", "Transaction dates are incomplete; ordering cannot be confirmed.", None)]
    if dates == sorted(dates, reverse=True) and dates != sorted(dates):
        rows.reverse()
    elif dates != sorted(dates):
        return [_check("statement_totals", "Transaction order is ambiguous; balance checks were skipped.", None)]
    findings = []
    previous = money(fields.get("opening_balance"))
    for row in rows:
        balance = money(row.get("balance"))
        if row["valid"] and previous is not None and balance is not None:
            expected = previous + money(row["credit"]) - money(row["debit"])
            ok = abs(balance - expected) <= TOLERANCE
            findings.append(_check("statement_running_balance",
                f"Row {row['row']}: stated balance ₹{balance:,.2f}; calculated ₹{expected:,.2f}.",
                ok, balance, expected, page=row["page"], transaction_id=row["transaction_id"]))
        else:
            findings.append(_check("statement_running_balance", f"Row {row['row']}: insufficient adjacent balance data.", None,
                                   page=row["page"], transaction_id=row["transaction_id"]))
        previous = balance  # a printed balance anchors the next readable row
    opening, closing = money(fields.get("opening_balance")), money(fields.get("closing_balance"))
    if fields["transactions_complete"] and not warnings and opening is not None and closing is not None:
        expected = opening + sum((money(row["credit"]) - money(row["debit"]) for row in rows), Decimal(0))
        findings.append(_check("statement_totals", f"Closing balance ₹{closing:,.2f}; opening plus net transactions ₹{expected:,.2f}.",
                               abs(closing - expected) <= TOLERANCE, closing, expected))
    else:
        findings.append(_check("statement_totals", "Whole-statement reconciliation requires every row and both endpoint balances.", None))
    return findings


def pay_month(value: Any) -> tuple[Date, Date] | None:
    raw = str(value or "").strip()
    matched = re.match(r"^(\d{4})-(\d{2})(?:-\d{2})?$", raw)
    if matched:
        year, month = map(int, matched.groups())
    else:
        matched = re.search(r"([A-Za-z]+)\s+(\d{4})", raw)
        if not matched:
            return None
        month = next((i for i in range(1, 13) if matched[1].lower() in {calendar.month_name[i].lower(), calendar.month_abbr[i].lower()}), 0)
        year = int(matched[2])
    try:
        first = Date(year, month, 1)
        end = Date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=7)
        return first, end
    except ValueError:
        return None


def reconcile_salary(reports: list[dict]) -> list[dict]:
    slips = [(i, r) for i, r in enumerate(reports) if r.get("document", {}).get("doc_type") == "payslip"]
    banks = [(i, r) for i, r in enumerate(reports) if r.get("document", {}).get("doc_type") == "bank_statement"]
    output = []
    for si, slip in slips:
        sf = slip.get("extraction", {}).get("fields", {})
        net, period = money(sf.get("net_pay")), pay_month(sf.get("pay_period"))
        for bi, bank in banks:
            bf, _ = normalize_statement(bank.get("extraction", {}).get("fields", {}))
            result = {"id": f"salary_{si}_{bi}", "check_code": "salary_bank_credit",
                "document_ids": [slip.get("_doc_id", f"doc_{si}"), bank.get("_doc_id", f"doc_{bi}")],
                "label": "Payslip → bank salary credit", "status": "review", "severity": "medium",
                "expected": str(net) if net is not None else None, "observed": None, "difference": None,
                "detail": "Salary credit comparison needs more evidence."}
            left = re.sub(r"\D", "", str(sf.get("bank_account_last4") or ""))[-4:]
            right = re.sub(r"\D", "", str(bf.get("account_last4") or ""))[-4:]
            start, end = iso_date(bf.get("statement_start")), iso_date(bf.get("statement_end"))
            if left and right and left != right:
                result["detail"] = "Payslip and statement account suffixes differ; confirm the salary account."
            elif not left or not right:
                result["detail"] = "Both account suffixes are required to confirm a salary credit match."
            elif net is None or period is None:
                result["detail"] = "Payslip net pay or pay month is unreadable."
            elif start is None or end is None or start > period[0] or end < period[1]:
                result["detail"] = "The statement does not cover the pay month plus the following seven days."
            else:
                employer = set(re.findall(r"[a-z]{3,}", str(sf.get("employer_name") or "").lower())) - {"ltd", "limited", "private", "company", "pvt"}
                candidates = []
                for row in bf["transactions"]:
                    desc = row["description"].lower()
                    when, credit = iso_date(row["date"]), money(row["credit"])
                    identified = bool(re.search(r"\b(salary|payroll)\b", desc)) or bool(employer & set(re.findall(r"[a-z]{3,}", desc)))
                    if row["valid"] and when and period[0] <= when <= period[1] and credit and credit > 0 and identified:
                        candidates.append(row)
                if len(candidates) != 1:
                    result["detail"] = "No unique identifiable salary payment was found; missing or split payments need review."
                else:
                    row = candidates[0]; credit = money(row["credit"]); difference = credit - net
                    matched = abs(difference) <= max(Decimal(100), net * Decimal("0.01"))
                    result.update(status="matched" if matched else "inconsistent", severity="info" if matched else "medium",
                        observed=str(credit), difference=str(difference), date=row["date"], page=row["page"],
                        transaction_id=row["transaction_id"], bank_document_id=result["document_ids"][1],
                        detail=f"Payslip net ₹{net:,.2f}; identified salary credit ₹{credit:,.2f}; difference ₹{difference:,.2f}.")
            output.append(result)
    return output
