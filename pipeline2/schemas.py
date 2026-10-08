"""
Per-document-type schemas that drive extraction and verification.

Each schema declares:
  label         : human-readable name
  fields        : ordered field -> short description (what the model should pull)
  key_fields    : the field(s) used to look the record up in the DB-of-record
  forgery_hints : known tampering patterns the model should watch for on this doc
  db_collection : logical name your friend's mocked DB uses for this record type

Adding a new document type = add one entry here. No other code changes needed.
"""

from __future__ import annotations

from typing import Any

SCHEMAS: dict[str, dict[str, Any]] = {
    # ----------------------------- Identity ------------------------------- #
    "pan_card": {
        "label": "PAN Card",
        "db_collection": "pan",
        "key_fields": ["pan"],
        "fields": {
            "pan": "10-char PAN (AAAAA9999A)",
            "name": "name as printed",
            "father_name": "father's name",
            "date_of_birth": "DOB (YYYY-MM-DD)",
        },
        "forgery_hints": [
            "Superimposed / replaced photograph (impersonation)",
            "Font mismatch between name and PAN number",
            "Invalid PAN checksum or wrong 4th char (P/C/H/F/A/T) for holder type",
        ],
    },
    "aadhaar_card": {
        "label": "Aadhaar Card",
        "db_collection": "aadhaar",
        "key_fields": ["aadhaar_last4", "name"],
        "fields": {
            "aadhaar_number": "full 12-digit Aadhaar number, digits only (needed for the Verhoeff checksum validation)",
            "aadhaar_last4": "last 4 digits of the Aadhaar number",
            "name": "name as printed",
            "date_of_birth": "DOB (YYYY-MM-DD)",
            "gender": "gender",
            "address": "full address",
        },
        "forgery_hints": [
            "Superimposed photo / impersonation",
            "Edited address block (different font/alignment)",
            "Invalid Verhoeff checksum on the 12-digit number",
        ],
    },
    # ------------------------------ Income -------------------------------- #
    "salaried_itr": {
        "label": "Salaried ITR",
        "db_collection": "itr",
        "key_fields": ["pan", "assessment_year"],
        "fields": {
            "pan": "PAN of filer",
            "name": "name of assessee",
            "assessment_year": "assessment year (e.g. 2024-25)",
            "gross_total_income": "gross total income (number)",
            "total_tax_paid": "total tax paid (number)",
            "employer_name": "employer name if present",
            "acknowledgement_number": "ITR-V acknowledgement number",
        },
        "forgery_hints": [
            "Inflated gross income vs filed return",
            "Altered acknowledgement number",
            "Tax paid inconsistent with income slab",
        ],
    },
    "form_16": {
        "label": "Form 16",
        "db_collection": "form16",
        "key_fields": ["pan", "tan", "assessment_year"],
        "fields": {
            "pan": "employee PAN",
            "tan": "employer TAN",
            "employee_name": "employee name",
            "employer_name": "employer / deductor name",
            "assessment_year": "assessment year",
            "gross_salary": "gross salary (number)",
            "tds_deducted": "total TDS deducted (number)",
        },
        "forgery_hints": [
            "Edited gross salary or TDS figures",
            "TAN not matching employer",
            "Part-A / Part-B totals inconsistent",
        ],
    },
    "payslip": {
        "label": "Salary Slip / Payslip",
        "db_collection": "payslip",
        "key_fields": ["employee_id", "pay_period"],
        "fields": {
            "employee_name": "employee name",
            "pan": "employee PAN if printed; null if absent",
            "employee_id": "employee id / code",
            "employer_name": "employer name",
            "pay_period": "month/year of the slip",
            "gross_pay": "gross pay (number)",
            "net_pay": "net pay / take-home (number)",
            "deductions": "total deductions (number)",
            "bank_account_last4": "salary credit account last 4 digits",
        },
        "forgery_hints": [
            "No issuer verification path -> cross-check with bank statement credit",
            "Net pay not equal to gross minus deductions (arithmetic tamper)",
            "Round-number salaries / inconsistent fonts",
        ],
    },
    "nri_salary_certificate": {
        "label": "NRI Salary Certificate",
        "db_collection": "nri_salary",
        "key_fields": ["employee_name", "employer_name"],
        "fields": {
            "employee_name": "employee name",
            "employer_name": "overseas employer name",
            "designation": "designation",
            "monthly_salary": "monthly salary (number)",
            "currency": "salary currency",
            "issue_date": "certificate issue date",
        },
        "forgery_hints": [
            "No verification path -> prone to misinformation",
            "Salary inconsistent with overseas account statement credits",
            "Generic letterhead / missing authorised signatory",
        ],
    },
    "net_worth_ca_certificate": {
        "label": "Net Worth / CA Certificate",
        "db_collection": "ca_certificate",
        "key_fields": ["membership_number", "udin"],
        "fields": {
            "client_name": "name of person the certificate is for",
            "ca_name": "issuing CA name",
            "membership_number": "ICAI membership number",
            "udin": "Unique Document Identification Number",
            "net_worth": "certified net worth (number)",
            "issue_date": "issue date",
        },
        "forgery_hints": [
            "Invalid / reused UDIN",
            "Membership number not matching CA name",
            "Net worth figure altered",
        ],
    },
    # ------------------------------ Banking ------------------------------- #
    "bank_statement": {
        "label": "Bank Statement (PDF)",
        "db_collection": "bank_statement",
        "key_fields": ["account_last4", "statement_period"],
        "fields": {
            "account_holder": "account holder name",
            "pan": "account holder PAN if printed; null if absent",
            "account_last4": "account number last 4 digits",
            "bank_name": "bank name",
            "statement_period": "statement period",
            "opening_balance": "opening balance (number)",
            "closing_balance": "closing balance (number)",
            "salary_credits": "list of salary credit amounts if identifiable",
        },
        "forgery_hints": [
            "Running balance does not reconcile with transactions",
            "Inserted / edited credit lines (font, alignment, decimal style)",
            "Closing balance not equal to opening +/- net transactions",
        ],
    },
    "cheque": {
        "label": "Cheque",
        "db_collection": "cheque",
        "key_fields": ["account_last4", "cheque_number"],
        "fields": {
            "payer_name": "drawer / account holder",
            "payee_name": "pay-to name",
            "amount_numeric": "amount in figures (number)",
            "amount_words": "amount in words",
            "cheque_number": "cheque number",
            "ifsc": "IFSC code",
            "account_last4": "account number last 4 digits",
            "date": "cheque date",
        },
        "forgery_hints": [
            "Signature alteration or full forgery",
            "Amount-in-figures != amount-in-words",
            "MICR / cheque number tampering",
        ],
    },
    "demand_draft": {
        "label": "Demand Draft",
        "db_collection": "demand_draft",
        "key_fields": ["dd_number", "bank_name"],
        "fields": {
            "dd_number": "DD number",
            "bank_name": "issuing bank",
            "payee_name": "payee",
            "amount_numeric": "amount in figures (number)",
            "amount_words": "amount in words",
            "issue_date": "issue date",
        },
        "forgery_hints": [
            "Altered amount / payee",
            "Fabricated DD number not on bank record",
        ],
    },
    # --------------------------- Property / Land --------------------------- #
    "land_record": {
        "label": "Land Record (7/12 · RTC · Patta-Chitta)",
        "db_collection": "land_record",
        "key_fields": ["state", "district", "taluka", "village", "survey_number"],
        "fields": {
            "state": "state the land is in (e.g. Karnataka, Maharashtra, Tamil Nadu)",
            "district": "district name (null if not printed)",
            "taluka": "taluka / taluk / tehsil",
            "village": "village name",
            "survey_number": "survey / gat number exactly as printed, keep sub-numbers like 102/3",
            "owner_name": "primary owner / khatedar name as printed",
            "area_hectare": "the named owner's HOLDING area in hectares (the khatedar's share), NOT the total survey/parcel area — on a 7/12 read the owner's portion, not the gross parcel area",
            "parcel_id": "unique parcel/land id (Bhoomi ID, ULPIN, PID) if present, else null",
            "encumbrance": "any loan / charge / encumbrance text if present, else null",
        },
        "forgery_hints": [
            "Edited owner / khatedar name (ownership fraud)",
            "Altered area or survey number",
            "Manipulated encumbrance entries to hide existing loans/charges",
        ],
    },
    "plan_approval": {
        "label": "Building Plan Approval",
        "db_collection": "plan_approval",
        "key_fields": ["approval_number", "authority"],
        "fields": {
            "approval_number": "sanction / approval number",
            "authority": "issuing municipal authority",
            "owner_name": "owner name",
            "property_address": "property address",
            "built_up_area": "approved built-up area",
            "approval_date": "approval date",
        },
        "forgery_hints": [
            "Not independently verified -> prone to manipulation",
            "Edited area / setbacks",
            "Forged authority stamp or signature",
        ],
    },
    "occupancy_certificate": {
        "label": "Occupancy Certificate (OC)",
        "db_collection": "occupancy_certificate",
        "key_fields": ["oc_number", "authority"],
        "fields": {
            "oc_number": "OC number",
            "authority": "issuing authority",
            "owner_name": "owner name",
            "property_address": "property address",
            "issue_date": "issue date",
        },
        "forgery_hints": [
            "Not verified -> manipulation risk",
            "Mismatch with plan approval details",
        ],
    },
    "sale_agreement": {
        "label": "Sale / Sale Agreement",
        "db_collection": "sale_agreement",
        "key_fields": ["registration_number", "sub_registrar_office"],
        "fields": {
            "registration_number": "registration / document number",
            "sub_registrar_office": "SRO name",
            "seller_name": "seller(s)",
            "buyer_name": "buyer(s)",
            "property_address": "property address",
            "consideration_value": "consideration / sale value (number)",
            "execution_date": "execution date",
        },
        "forgery_hints": [
            "Lower edit chance but possible -> altered consideration value",
            "Party-name substitution",
            "Inconsistent stamp duty vs value",
        ],
    },
    "chain_document": {
        "label": "Title Chain Document",
        "db_collection": "chain_document",
        "key_fields": ["document_number", "property_id"],
        "fields": {
            "document_number": "document number",
            "property_id": "survey / property identifier",
            "from_party": "transferor",
            "to_party": "transferee",
            "transaction_date": "transaction date",
        },
        "forgery_hints": [
            "Entire chain not verifiable -> high tamper risk",
            "Broken ownership continuity between links",
        ],
    },
    "property_tax_receipt": {
        "label": "Property Tax Receipt / Khata",
        "db_collection": "property_tax",
        "key_fields": ["khata_number", "property_id"],
        "fields": {
            "khata_number": "khata / PID number",
            "property_id": "property identifier",
            "owner_name": "owner name",
            "property_address": "property address",
            "amount_paid": "tax amount paid (number)",
            "assessment_year": "assessment year",
        },
        "forgery_hints": [
            "Municipal record not verified",
            "Owner-name or PID edited (used as ownership/address proof)",
        ],
    },
    "vehicle_rc": {
        "label": "Vehicle RC / Insurance",
        "db_collection": "vehicle_rc",
        "key_fields": ["registration_number"],
        "fields": {
            "registration_number": "vehicle registration number",
            "owner_name": "registered owner",
            "make_model": "make and model",
            "chassis_last4": "chassis number last 4",
            "address": "owner address",
            "valid_upto": "RC/insurance validity",
        },
        "forgery_hints": [
            "Used as collateral/address proof -> owner/address edit",
            "Mismatch RC vs insurance details",
        ],
    },
    # --------------------------- Legal / Misc ----------------------------- #
    "agreement": {
        "label": "Generic Agreement",
        "db_collection": "agreement",
        "key_fields": ["agreement_id"],
        "fields": {
            "agreement_id": "agreement number/id if any",
            "party_a": "first party",
            "party_b": "second party",
            "subject": "subject of agreement",
            "execution_date": "execution date",
        },
        "forgery_hints": ["Prone to clause/value editing"],
    },
    "rent_lease_agreement": {
        "label": "Rent / Lease Agreement",
        "db_collection": "rent_agreement",
        "key_fields": ["agreement_id"],
        "fields": {
            "agreement_id": "agreement id if any",
            "landlord_name": "landlord",
            "tenant_name": "tenant",
            "property_address": "rented property address",
            "monthly_rent": "monthly rent (number)",
            "start_date": "lease start date",
            "duration_months": "duration in months",
        },
        "forgery_hints": [
            "Commonly used as address proof -> address/tenant edit",
            "Backdated execution / missing notarisation",
        ],
    },
    "address_proof": {
        "label": "Address Proof",
        "db_collection": "address_proof",
        "key_fields": ["name", "address"],
        "fields": {
            "name": "name on the proof",
            "address": "full address",
            "document_basis": "what the proof is (utility bill, etc.)",
            "issue_date": "issue / bill date",
        },
        "forgery_hints": [
            "Main culprit for mule accounts",
            "Edited name/address on utility bill",
            "Mismatch with other submitted addresses",
        ],
    },
    "power_of_attorney": {
        "label": "Power of Attorney (PoA)",
        "db_collection": "poa",
        "key_fields": ["registration_number"],
        "fields": {
            "registration_number": "PoA registration number",
            "grantor_name": "grantor / principal",
            "grantee_name": "grantee / attorney",
            "scope": "powers granted",
            "execution_date": "execution date",
            "is_registered": "registered (yes/no)",
        },
        "forgery_hints": [
            "Forged grantor signature",
            "Unregistered PoA presented as registered",
        ],
    },
    "aod": {
        "label": "Acknowledgement of Debt (AOD)",
        "db_collection": "aod",
        "key_fields": ["reference_number"],
        "fields": {
            "reference_number": "reference / loan number",
            "borrower_name": "borrower",
            "amount": "acknowledged amount (number)",
            "date": "acknowledgement date",
        },
        "forgery_hints": ["Fake / lifted signature", "Altered amount"],
    },
    "death_certificate": {
        "label": "Death / Legal Heir Certificate",
        "db_collection": "death_certificate",
        "key_fields": ["certificate_number", "authority"],
        "fields": {
            "certificate_number": "certificate number",
            "authority": "issuing municipal authority",
            "deceased_name": "name of deceased",
            "date_of_death": "date of death",
            "legal_heirs": "named legal heirs (for heir certificate)",
        },
        "forgery_hints": [
            "Municipal record not verified (settlement-claim fraud)",
            "Fabricated certificate number",
        ],
    },
    "compliance_letter": {
        "label": "Compliance / Freeze Letter (Police/ED/IT/Court)",
        "db_collection": "compliance_letter",
        "key_fields": ["reference_number", "issuing_authority"],
        "fields": {
            "reference_number": "letter reference / case number",
            "issuing_authority": "police / ED / Income Tax / court",
            "account_number_last4": "target account last 4 digits",
            "action_required": "freeze / allow-transaction / other",
            "issue_date": "issue date",
            "signatory": "signing officer / designation",
        },
        "forgery_hints": [
            "Authenticity NOT verified -> treat as high-risk by default",
            "Spoofed letterhead / officer name",
            "Fabricated case reference",
        ],
    },
    # --------------------------- Business / Tax --------------------------- #
    "gst_return": {
        "label": "GST Return / GSTR-3B",
        "db_collection": "gst_return",
        "key_fields": ["gstin", "return_period"],
        "fields": {
            "gstin": "15-char GSTIN",
            "legal_name": "registered legal name",
            "return_period": "return period (MMYYYY)",
            "total_taxable_value": "total taxable value (number)",
            "total_tax": "total tax (number)",
        },
        "forgery_hints": [
            "GSTIN checksum invalid",
            "Turnover figures edited vs portal",
        ],
    },
    "udyam_msme": {
        "label": "Udyam / MSME Registration",
        "db_collection": "udyam",
        "key_fields": ["udyam_number"],
        "fields": {
            "udyam_number": "Udyam registration number (UDYAM-XX-00-0000000)",
            "enterprise_name": "enterprise name",
            "owner_name": "owner / proprietor",
            "enterprise_type": "micro / small / medium",
            "registration_date": "registration date",
        },
        "forgery_hints": [
            "Invalid Udyam number format",
            "Enterprise type/turnover edited",
        ],
    },
    "dsc_estamp": {
        "label": "DSC on e-Stamped Document",
        "db_collection": "estamp",
        "key_fields": ["stamp_certificate_number"],
        "fields": {
            "stamp_certificate_number": "e-stamp certificate number",
            "issued_to": "issued-to party",
            "stamp_value": "stamp value (number)",
            "issue_date": "issue date",
            "dsc_signatory": "digital signature signatory",
            "dsc_valid": "DSC validity status if shown",
        },
        "forgery_hints": [
            "Reused / fabricated e-stamp certificate number",
            "Invalid or expired digital signature",
        ],
    },
    "employer_id": {
        "label": "Employer ID Card / Appointment Letter",
        "db_collection": "employer_id",
        "key_fields": ["employee_id", "employer_name"],
        "fields": {
            "employee_name": "employee name",
            "employee_id": "employee id",
            "employer_name": "employer name",
            "designation": "designation",
            "joining_date": "joining date",
        },
        "forgery_hints": [
            "Superimposed photo",
            "Fabricated employer / designation",
        ],
    },
}

# Fallback used when the document type is unknown / not in the registry.
GENERIC_SCHEMA: dict[str, Any] = {
    "label": "Unknown Document",
    "db_collection": "generic",
    "key_fields": ["name"],
    "fields": {
        "name": "primary person/entity name",
        "document_title": "what this document appears to be",
        "key_identifiers": "any ids, numbers, dates present",
        "amounts": "any monetary amounts present",
    },
    "forgery_hints": ["Unknown type -> extract all identifiers for manual review"],
}


def get_schema(doc_type: str | None) -> dict[str, Any]:
    if doc_type and doc_type in SCHEMAS:
        return SCHEMAS[doc_type]
    return GENERIC_SCHEMA


def known_types() -> list[str]:
    return sorted(SCHEMAS.keys())
