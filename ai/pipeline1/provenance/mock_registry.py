"""Local JSON-backed provenance registry for offline issuer lookups."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

REGISTRY_PATH = Path("data/mock_registry.json")


class RegistryRecord(BaseModel):
    """One local issuer/registry assertion for a document."""

    doc_sha256: str
    issuer: str
    status: Literal["genuine", "known_fake"]
    qr_payload: str | None
    notes: str = ""


def register(record: RegistryRecord) -> None:
    """Upsert a registry record by document SHA-256."""

    records = _read_records()
    by_hash = {existing.doc_sha256: existing for existing in records}
    by_hash[record.doc_sha256] = record
    _write_records(list(by_hash.values()))


def lookup_by_hash(doc_sha256: str) -> RegistryRecord | None:
    """Return a registry record matching a document hash, if present."""

    normalised = doc_sha256.strip().lower()
    for record in _read_records():
        if record.doc_sha256.lower() == normalised:
            return record
    return None


def lookup_by_qr_payload(payload: str) -> RegistryRecord | None:
    """Return a registry record matching a QR payload, if present."""

    for record in _read_records():
        if record.qr_payload == payload:
            return record
    return None


def sha256_of_file(path: str | Path) -> str:
    """Compute a file's SHA-256 digest."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MockRegistry:
    """Small compatibility wrapper around the JSON registry helpers."""

    def __init__(self, registry_path: str | Path | None = None):
        self.registry_path = Path(registry_path) if registry_path is not None else REGISTRY_PATH

    def lookup_by_qr_payload(self, payload: str) -> RegistryRecord | None:
        return _lookup_by_qr_payload_at(self.registry_path, payload)

    def lookup_by_hash(self, doc_sha256: str) -> RegistryRecord | None:
        return _lookup_by_hash_at(self.registry_path, doc_sha256)

    def lookup_by_content_hash(self, content_hash: str) -> RegistryRecord | None:
        return self.lookup_by_hash(content_hash)

    def insert(self, entry: dict[str, Any]) -> None:
        record = RegistryRecord(
            doc_sha256=entry.get("doc_sha256") or entry.get("content_hash"),
            issuer=entry.get("issuer") or "",
            status=entry.get("status") or "genuine",
            qr_payload=entry.get("qr_payload"),
            notes=entry.get("notes") or "",
        )
        _register_at(self.registry_path, record)


def _lookup_by_hash_at(path: Path, doc_sha256: str) -> RegistryRecord | None:
    normalised = doc_sha256.strip().lower()
    for record in _read_records(path):
        if record.doc_sha256.lower() == normalised:
            return record
    return None


def _lookup_by_qr_payload_at(path: Path, payload: str) -> RegistryRecord | None:
    for record in _read_records(path):
        if record.qr_payload == payload:
            return record
    return None


def _register_at(path: Path, record: RegistryRecord) -> None:
    records = _read_records(path)
    by_hash = {existing.doc_sha256: existing for existing in records}
    by_hash[record.doc_sha256] = record
    _write_records(list(by_hash.values()), path)


def _read_records(path: Path | None = None) -> list[RegistryRecord]:
    """Read registry records from supported JSON shapes."""

    path = path or REGISTRY_PATH
    if not path.exists():
        return []

    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(raw_data, dict):
        raw_records = raw_data.get("documents", [])
    else:
        raw_records = raw_data

    if not isinstance(raw_records, list):
        return []

    records: list[RegistryRecord] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        try:
            records.append(RegistryRecord.model_validate(raw_record))
        except Exception:
            continue
    return records


def _write_records(records: list[RegistryRecord], path: Path | None = None) -> None:
    """Write pretty-printed registry JSON."""

    path = path or REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.model_dump() for record in sorted(records, key=lambda item: item.doc_sha256)]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
