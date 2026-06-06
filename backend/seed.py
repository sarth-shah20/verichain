"""
Run this once to seed the database with mock applicants and document hashes.
Usage: python seed.py
"""

import sqlite3
import hashlib
import json
import os

DB_PATH = "verichain.db"

MOCK_APPLICANTS = [
    {
        "applicant_id": "APP001",
        "name": "Ramesh Vitthal Patil",
        "scenario": "Genuine ITR with DigiLocker URI",
        "documents": [
            {
                "doc_type": "itr",
                "digilocker_uri": "https://mock.digilocker.gov.in/APP001/itr2324",
                "fields": {
                    "pan": "ABCDE1234F",
                    "name": "Ramesh Vitthal Patil",
                    "assessment_year": "2023-24",
                    "gross_income": 420000,
                    "tax_paid": 12400
                },
                "lien_status": None
            }
        ],
        "expected_score": 96,
        "expected_decision": "auto_approve"
    },
    {
        "applicant_id": "APP002",
        "name": "Suresh Kumar",
        "scenario": "Tampered ITR — income altered from 4.2L to 12L",
        "documents": [
            {
                "doc_type": "itr",
                "digilocker_uri": "https://mock.digilocker.gov.in/APP002/itr2324",
                "fields": {
                    "pan": "FGHIJ5678K",
                    "name": "Suresh Kumar",
                    "assessment_year": "2023-24",
                    "gross_income": 420000,
                    "tax_paid": 12400
                },
                "lien_status": None
            }
        ],
        "expected_score": 18,
        "expected_decision": "auto_reject"
    },
    {
        "applicant_id": "APP003",
        "name": "Dnyaneshwar Balu Shinde",
        "scenario": "Marathi 7/12 land record scan",
        "documents": [
            {
                "doc_type": "land_record",
                "ulpin": "MH-PUN-001-2024-00345",
                "fields": {
                    "survey_number": "123/A",
                    "owner_name": "Dnyaneshwar Balu Shinde",
                    "area_acres": 2.5,
                    "taluka": "Haveli",
                    "district": "Pune",
                    "encumbrance": "None"
                },
                "lien_status": "clear"
            }
        ],
        "expected_score": 79,
        "expected_decision": "human_review"
    },
    {
        "applicant_id": "APP004",
        "name": "Priya Mehta",
        "scenario": "AI-generated fake salary slip",
        "documents": [
            {
                "doc_type": "salary_slip",
                "digilocker_uri": None,
                "fields": {
                    "employee_name": "Priya Mehta",
                    "employer": "TechCorp Pvt Ltd",
                    "month": "March 2024",
                    "gross_salary": 95000,
                    "net_salary": 82000
                },
                "lien_status": None
            }
        ],
        "expected_score": 22,
        "expected_decision": "auto_reject"
    },
    {
        "applicant_id": "APP005",
        "name": "Arjun Sharma",
        "scenario": "Cross-doc fraud — ITR vs salary slip income mismatch",
        "documents": [
            {
                "doc_type": "itr",
                "digilocker_uri": "https://mock.digilocker.gov.in/APP005/itr2324",
                "fields": {
                    "pan": "LMNOP9012Q",
                    "name": "Arjun Sharma",
                    "assessment_year": "2023-24",
                    "gross_income": 420000,
                    "tax_paid": 12400
                },
                "lien_status": None
            },
            {
                "doc_type": "salary_slip",
                "digilocker_uri": None,
                "fields": {
                    "employee_name": "Arjun Sharma",
                    "employer": "Sunrise Enterprises",
                    "month": "March 2024",
                    "gross_salary": 98000,
                    "net_salary": 85000
                },
                "lien_status": None
            }
        ],
        "expected_score": 41,
        "expected_decision": "auto_reject"
    }
]

def hash_fields(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()

def seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applicants (
            applicant_id TEXT PRIMARY KEY,
            name TEXT,
            scenario TEXT,
            expected_score INTEGER,
            expected_decision TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_id TEXT,
            doc_type TEXT,
            digilocker_uri TEXT,
            ulpin TEXT,
            fields_json TEXT,
            fields_hash TEXT,
            lien_status TEXT,
            FOREIGN KEY(applicant_id) REFERENCES applicants(applicant_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blockchain_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_id TEXT,
            doc_hash TEXT,
            risk_score INTEGER,
            decision TEXT,
            timestamp TEXT,
            tx_hash TEXT
        )
    """)

    for applicant in MOCK_APPLICANTS:
        cur.execute("""
            INSERT OR REPLACE INTO applicants VALUES (?, ?, ?, ?, ?)
        """, (
            applicant["applicant_id"],
            applicant["name"],
            applicant["scenario"],
            applicant["expected_score"],
            applicant["expected_decision"]
        ))

        for doc in applicant["documents"]:
            fields_json = json.dumps(doc["fields"])
            fields_hash = hash_fields(doc["fields"])
            cur.execute("""
                INSERT INTO documents
                (applicant_id, doc_type, digilocker_uri, ulpin, fields_json, fields_hash, lien_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                applicant["applicant_id"],
                doc["doc_type"],
                doc.get("digilocker_uri"),
                doc.get("ulpin"),
                fields_json,
                fields_hash,
                doc.get("lien_status")
            ))

    conn.commit()
    conn.close()
    print("Database seeded with 5 test applicants.")
    print("Run the backend and test with applicant IDs: APP001 through APP005")

if __name__ == "__main__":
    seed()