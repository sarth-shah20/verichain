from copy import deepcopy

import pytest

from bank_reconciliation import normalize_statement, reconcile_salary, statement_checks
from verify import verify_document


def statement():
    return {"currency": "INR", "opening_balance": 10000, "closing_balance": 78000,
        "account_last4": "1234", "statement_start": "2025-03-01", "statement_end": "2025-04-07",
        "transactions_complete": True, "transactions": [
            {"date": "2025-03-20", "description": "Rent", "debit": 2000, "credit": None, "balance": 8000, "page": 1},
            {"date": "2025-03-31", "description": "EXAMPLE PAYROLL", "debit": None, "credit": 70000, "balance": 78000, "page": 2}]}


def pair(bank=None, slip=None):
    return [{"document": {"doc_type": "payslip"}, "extraction": {"fields": slip or {
        "net_pay": 70000, "gross_pay": 80000, "pay_period": "March 2025",
        "employer_name": "Example Ltd", "bank_account_last4": "1234"}}},
        {"document": {"doc_type": "bank_statement"}, "extraction": {"fields": bank or statement()}}]


def test_clean_statement_reconciles():
    checks = statement_checks(statement())
    assert len(checks) == 3
    assert all(c["passed"] is True for c in checks)


def test_altered_running_balance_and_total_fail_without_db():
    fields = statement(); fields["transactions"][1]["balance"] = 178000; fields["closing_balance"] = 178000
    result = verify_document({"_schema": {"doc_type": "bank_statement"}, "fields": fields}, {"found": False})
    assert result["match_status"] == "mismatch"
    assert len([c for c in result["deterministic_checks"] if c["passed"] is False]) == 2


def test_descending_statement_and_rounding():
    fields = statement(); fields["transactions"].reverse(); fields["closing_balance"] += 0.5
    assert all(c["passed"] is True for c in statement_checks(fields))


def test_unreadable_row_is_retained_and_totals_skipped():
    fields = statement(); fields["transactions"][0]["debit"] = "unreadable"
    normalized, warnings = normalize_statement(fields)
    assert warnings and len(normalized["transactions"]) == 2
    assert normalized["transactions_complete"] is False
    assert statement_checks(fields)[-1]["passed"] is None


def test_salary_uses_net_and_source_page():
    result = reconcile_salary(pair())[0]
    assert result["status"] == "matched"
    assert result["expected"] == "70000" and result["page"] == 2


@pytest.mark.parametrize("change", ["missing", "account", "coverage", "multiple", "unrelated"])
def test_ambiguous_salary_requires_review(change):
    fields = statement()
    if change == "missing": fields["transactions"].pop()
    if change == "account": fields["account_last4"] = "9999"
    if change == "coverage": fields["statement_end"] = "2025-03-31"
    if change == "multiple": fields["transactions"].append(deepcopy(fields["transactions"][1]))
    if change == "unrelated": fields["transactions"][1]["description"] = "Personal transfer"
    assert reconcile_salary(pair(fields))[0]["status"] == "review"


def test_identified_underpayment_is_inconsistent_not_definitive():
    fields = statement(); fields["transactions"][1]["credit"] = 30000
    result = reconcile_salary(pair(fields))[0]
    assert result["status"] == "inconsistent" and result["severity"] == "medium"


def test_salary_tolerance_and_next_month_window():
    fields = statement(); fields["transactions"][1].update(date="2025-04-05", credit=70100)
    assert reconcile_salary(pair(fields))[0]["status"] == "matched"


def test_missing_balances_or_mixed_order_do_not_invent_failures():
    fields = statement(); fields["opening_balance"] = None; fields["transactions"][0]["balance"] = None
    assert all(c["passed"] is None for c in statement_checks(fields))
    fields = statement(); fields["transactions"].append({"date": "2025-03-10", "credit": 1000})
    assert statement_checks(fields)[0]["passed"] is None
