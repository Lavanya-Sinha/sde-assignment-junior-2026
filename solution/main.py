import json
from pathlib import Path
import re
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import os
import hashlib
import hmac
from cryptography.fernet import Fernet
import sqlite3
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter
from datetime import date

def load_schema(path: Path) -> dict:
    with path.open('r', encoding='utf-8') as file:
        return json.load(file)

def load_all_schemas(directory: Path) -> dict:
    schemas = {}
    for filePath in directory.glob('*.json'):
        schema = load_schema(filePath)
        workflow_id = schema['workflow_id']
        schemas[workflow_id] = schema

    return schemas


def normalize_header(header: str) -> str:
    header = header.strip().lower()
    return re.sub(r'[_\s]+', ' ', header)

def map_headers(headers: list, schema: dict) -> dict:
    mapping = {}
    for field in schema['fields']:
        accepted_names = [field['name']] + field.get('aliases',[])

        for header in headers:
            if normalize_header(header) in [
                normalize_header(name) for name in accepted_names
            ]:
                mapping[field["name"]] = header
                break

    return mapping

# test data




def read_csv_rows(path: Path) -> list:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader)

# csv_path = Path("data/drop_1/leads/motor_renewal/batch_001.csv")
# rows = read_csv_rows(csv_path)

# print("First row:", rows[0])
# print("Total rows:", len(rows))


def extract_fields(row: dict, mapping: dict) -> dict:
    extracted = {}

    for field_name, csv_header in mapping.items():
        value = row.get(csv_header)
        extracted[field_name] = value.strip() if value else None

    return extracted





def normalize_phone(value: str) -> str | None:
    if not value:
        return None

    digits = re.sub(r"\D", "", value)

    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] not in "6789":
        return None

    return "+91" + digits



def normalize_date(value: str) -> str | None:
    if not value:
        return None

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
    ]

    for date_format in formats:
        try:
            parsed_date = datetime.strptime(value.strip(), date_format)
            return parsed_date.date().isoformat()
        except ValueError:
            continue

    return None




def normalize_decimals(value:str) -> Decimal | None:
    if not value:
        return None

    cleaned = value.strip()
    cleaned = re.sub(
        r"^(?:₹|rs\.?|inr)\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = cleaned.replace(',', '')

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
     return None

    if not amount.is_finite() or amount < 0:
        return None

    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)




def normalize_field(value: str, field: dict):
    field_type = field["type"]

    if field_type == "string":
        return value.strip()

    if field_type == "phone":
        return normalize_phone(value)

    if field_type == "date":
        return normalize_date(value)

    if field_type == "decimal":
        return normalize_decimals(value)

    if field_type == "enum":
        allowed_values = field["values"]
        normalized = value.lower()

        if normalized in allowed_values:
            return normalized

        return None

    return None

def validate_lead(extracted: dict, schema: dict):
    cleaned = {}
    warnings = []

    for field in schema["fields"]:
        name = field["name"]
        value = extracted.get(name)

        # Check required fields
        if not value:
            if field.get("required", False):
                return None, f"missing_required:{name}", warnings

            cleaned[name] = None
            continue

        # Normalize according to field type
        normalized = normalize_field(value, field)

        if normalized is None:
            if field["type"] == "phone":
                return None, "invalid_phone", warnings

            if field.get("required", False):
                return None, f"invalid_{name}", warnings

            cleaned[name] = None
            warnings.append(name)
            continue

        cleaned[name] = normalized

    return cleaned, None, warnings










def process_csv_file(path: Path, schema: dict):
    rows = read_csv_rows(path)
    mapping = map_headers(list(rows[0].keys()), schema)

    valid_leads = []
    rejected_rows = []
    field_warnings = {}

    row_number = 0

    for row in rows:
        if not any(value and value.strip() for value in row.values()):
            continue

        row_number += 1

        extracted = extract_fields(row, mapping)

        cleaned, rejection, warnings = validate_lead(
            extracted,
            schema
        )

        if rejection:
            rejected_rows.append({
                 "workflow_id": schema["workflow_id"],
                 "batch_id": path.stem,
                 "row_number": row_number,
                 "reason": rejection
            })
            continue

        cleaned["workflow_id"] = schema["workflow_id"]
        cleaned["batch_id"] = path.stem

        valid_leads.append(cleaned)

        for field_name in warnings:
            field_warnings[field_name] = (
                field_warnings.get(field_name, 0) + 1
            )

    return valid_leads, rejected_rows, field_warnings





def process_all_lead_files(data_dir: Path, schemas: dict):
    all_leads = []
    all_rejections = []
    all_warnings = {}

    for drop_dir in sorted(data_dir.glob("drop_*")):
        for workflow_dir in sorted((drop_dir / "leads").iterdir()):
            workflow_id = workflow_dir.name
            schema = schemas[workflow_id]

            for csv_path in sorted(workflow_dir.glob("batch_*.csv")):
                leads, rejections, warnings = process_csv_file(
                    csv_path, schema
                )

                all_leads.extend(leads)
                all_rejections.extend(rejections)

                for field_name, count in warnings.items():
                    all_warnings[field_name] = (
                        all_warnings.get(field_name, 0) + count
                    )

    return all_leads, all_rejections, all_warnings




def merge_duplicate_leads(leads: list):
    unique_leads = {}
    duplicate_count = 0

    for lead in leads:
        identity = (lead["workflow_id"], lead["phone"])

        if identity not in unique_leads:
            unique_leads[identity] = lead.copy()
            continue

        duplicate_count += 1

        existing = unique_leads[identity]

        for field, value in lead.items():
            if value is not None and field != "batch_id":
                existing[field] = value

    return list(unique_leads.values()), duplicate_count



def apply_defaults(leads: list, schemas: dict):
    for lead in leads:
        schema = schemas[lead["workflow_id"]]

        for field in schema["fields"]:
            name = field["name"]

            if lead.get(name) is None and "default" in field:
                lead[name] = field["default"]

    return leads


# print(unique_leads[0])

def load_dispositions(path: Path) -> dict:
    dispositions = {}

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            key = (row["workflow_id"], row["code"])
            dispositions[key] = {
                "label": row["label"],
                "is_terminal": row["is_terminal"].lower() == "true",
                "is_success": row["is_success"].lower() == "true"
            }

    return dispositions



# Database Encryption And Hashing

def encrypt_value(value: str) -> str:
    key = os.environ["APP_ENCRYPTION_KEY"].encode()
    return Fernet(key).encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    key = os.environ["APP_ENCRYPTION_KEY"].encode()
    return Fernet(key).decrypt(value.encode()).decode()


def hash_phone(phone: str) -> str:
    key = bytes.fromhex(os.environ["PHONE_HASH_KEY"])

    return hmac.new(
        key,
        phone.encode(),
        hashlib.sha256
    ).hexdigest()




# DB Initialisation

def create_database(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                phone_hash TEXT NOT NULL,
                pii_encrypted TEXT NOT NULL,
                data_json TEXT NOT NULL,
                external_ref TEXT,
                batch_id TEXT NOT NULL,
                UNIQUE(workflow_id, phone_hash)
            );

            CREATE TABLE IF NOT EXISTS interaction_events (
                event_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                call_id TEXT,
                lead_id INTEGER,
                event_type TEXT NOT NULL,
                occurred_at TEXT,
                payload_json TEXT,
                raw_json TEXT NOT NULL,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );

            CREATE TABLE IF NOT EXISTS processed_inputs (
                source_key TEXT PRIMARY KEY
            );
        """)



def save_leads(db_path: Path, leads: list, schemas: dict):
    with sqlite3.connect(db_path) as conn:
        for lead in leads:
            schema = schemas[lead["workflow_id"]]

            pii_fields = [
                field["name"]
                for field in schema["fields"]
                if field.get("pii", False)
            ]

            pii_data = {
                name: lead[name]
                for name in pii_fields
            }

            encrypted_pii = encrypt_value(json.dumps(pii_data))

            phone_hash = hash_phone(lead["phone"])

            external_ref_field = next(
                field["name"]
                for field in schema["fields"]
                if field.get("reference", False)
            )

            external_ref = lead[external_ref_field]

            public_data = {
                key: value
                for key, value in lead.items()
                if key not in pii_fields
                and key not in ("workflow_id", "batch_id")
            }

            conn.execute("""
                INSERT OR IGNORE INTO leads
                (workflow_id, phone_hash, pii_encrypted,
                 data_json, external_ref, batch_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                lead["workflow_id"],
                phone_hash,
                encrypted_pii,
                json.dumps(public_data, default=str),
                external_ref,
                lead["batch_id"]
            ))





# Cycle Of Events

def normalize_timestamp(value: str) -> str | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))

        return parsed.astimezone(
            ZoneInfo("Asia/Kolkata")
        ).isoformat()

    except ValueError:
        return None



# Event Ingestion


def ingest_events(data_dir: Path, db_path: Path, dispositions: dict):
    stats = {
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "unknown_disposition_events": 0
    }

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_quality (
                source_key TEXT PRIMARY KEY,
                outcome TEXT NOT NULL,
                event_id TEXT
            )
        """)

        for drop_dir in sorted(data_dir.glob("drop_*")):
            events_dir = drop_dir / "events"

            if not events_dir.exists():
                continue

            for event_file in sorted(events_dir.glob("*.jsonl")):
                with event_file.open("r", encoding="utf-8") as file:
                    for line_number, raw_line in enumerate(file, start=1):
                        raw_line = raw_line.strip()

                        if not raw_line:
                            continue

                        relative_path = event_file.relative_to(data_dir)
                        source_text = f"{relative_path}:{line_number}:{raw_line}"
                        source_key = hashlib.sha256(
                            source_text.encode()
                        ).hexdigest()

                        already_processed = conn.execute(
                            "SELECT 1 FROM processed_inputs WHERE source_key = ?",
                            (source_key,)
                        ).fetchone()

                        if already_processed:
                            continue

                        stats["events_total"] += 1
                        outcome = "stored"
                        event_id = None

                        try:
                            event = json.loads(raw_line)

                            if not isinstance(event, dict) or not event.get("event_id"):
                                raise ValueError("Missing event_id")

                            event_id = event["event_id"]

                            required = [
                                "event_type", "workflow_id",
                                "call_id", "occurred_at"
                            ]
                            if any(not event.get(key) for key in required):
                                raise ValueError("Missing required event field")

                            event_type = event["event_type"]
                            workflow_id = event["workflow_id"]
                            call_id = event["call_id"]
                            occurred_at = normalize_timestamp(event["occurred_at"])

                            if occurred_at is None:
                                raise ValueError("Invalid timestamp")

                            if event_type not in {
                                "call.initiated",
                                "call.telephony_failed",
                                "call.connected",
                                "call.ended",
                                "disposition.set",
                                "disposition.override"
                            }:
                                raise ValueError("Unknown event type")

                            payload = event.get("payload") or {}

                            if event_type in {
                                "disposition.set",
                                "disposition.override"
                            }:
                                code = payload.get("disposition_code")

                                if (workflow_id, code) not in dispositions:
                                    outcome = "unknown_disposition"
                                    stats["unknown_disposition_events"] += 1
                                    raise StopIteration

                            duplicate = conn.execute(
                                "SELECT 1 FROM interaction_events WHERE event_id = ?",
                                (event_id,)
                            ).fetchone()

                            if duplicate:
                                outcome = "duplicate"
                                stats["duplicate_events_dropped"] += 1
                                raise StopIteration

                            lead_id = None

                            if event_type != "disposition.override" and event.get("phone"):
                                canonical_phone = normalize_phone(event["phone"])

                                if canonical_phone:
                                    phone_digest = hash_phone(canonical_phone)
                                    match = conn.execute("""
                                        SELECT id FROM leads
                                        WHERE workflow_id = ? AND phone_hash = ?
                                    """, (workflow_id, phone_digest)).fetchone()

                                    if match:
                                        lead_id = match[0]

                            conn.execute("""
                                INSERT INTO interaction_events (
                                    event_id, workflow_id, call_id, lead_id,
                                    event_type, occurred_at, payload_json, raw_json
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                event_id, workflow_id, call_id, lead_id,
                                event_type, occurred_at,
                                json.dumps(payload), encrypt_value(raw_line)
                            ))

                        except StopIteration:
                            pass
                        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                            outcome = "malformed"
                            stats["malformed_events"] += 1

                        conn.execute(
                            "INSERT INTO processed_inputs (source_key) VALUES (?)",
                            (source_key,)
                        )

                        conn.execute("""
                            INSERT INTO event_quality (source_key, outcome, event_id)
                            VALUES (?, ?, ?)
                        """, (source_key, outcome, event_id))

        # Overrides have no phone. Link them using another event from the same call.
        conn.execute("""
            UPDATE interaction_events AS target
            SET lead_id = (
                SELECT source.lead_id
                FROM interaction_events AS source
                WHERE source.call_id = target.call_id
                  AND source.workflow_id = target.workflow_id
                  AND source.lead_id IS NOT NULL
                LIMIT 1
            )
            WHERE target.lead_id IS NULL
              AND target.event_type = 'disposition.override'
        """)

        # Persist the final orphan classification.
        conn.execute("""
            UPDATE event_quality
            SET outcome = 'orphan'
            WHERE event_id IN (
                SELECT event_id FROM interaction_events
                WHERE lead_id IS NULL
            )
            AND outcome = 'stored'
        """)

        orphan_count = conn.execute("""
            SELECT COUNT(*) FROM interaction_events
            WHERE lead_id IS NULL
        """).fetchone()[0]

        stats["orphan_events"] = orphan_count

    return stats

def relink_orphan_events(db_path: Path):
    with sqlite3.connect(db_path) as conn:
        orphans = conn.execute("""
            SELECT event_id, workflow_id, event_type, raw_json
            FROM interaction_events
            WHERE lead_id IS NULL
              AND event_type != 'disposition.override'
        """).fetchall()

        for event_id, workflow_id, event_type, raw_json in orphans:
            raw_event = json.loads(decrypt_value(raw_json))
            phone = normalize_phone(raw_event.get("phone"))

            if not phone:
                continue

            match = conn.execute("""
                SELECT id FROM leads
                WHERE workflow_id = ? AND phone_hash = ?
            """, (workflow_id, hash_phone(phone))).fetchone()

            if match:
                conn.execute("""
                    UPDATE interaction_events
                    SET lead_id = ?
                    WHERE event_id = ?
                """, (match[0], event_id))

                conn.execute("""
                    UPDATE event_quality
                    SET outcome = 'stored'
                    WHERE event_id = ?
                """, (event_id,))

        conn.execute("""
            UPDATE interaction_events AS target
            SET lead_id = (
                SELECT source.lead_id
                FROM interaction_events AS source
                WHERE source.call_id = target.call_id
                  AND source.workflow_id = target.workflow_id
                  AND source.lead_id IS NOT NULL
                LIMIT 1
            )
            WHERE target.lead_id IS NULL
              AND target.event_type = 'disposition.override'
        """)

        conn.execute("""
            UPDATE event_quality
            SET outcome = 'stored'
            WHERE event_id IN (
                SELECT event_id FROM interaction_events
                WHERE lead_id IS NOT NULL
            )
            AND outcome = 'orphan'
        """)








# Report Aggregation

def build_call_records(events: list, dispositions: dict) -> dict:
    calls = {}

    for event in events:
        key = (event["workflow_id"], event["call_id"])
        calls.setdefault(key, []).append(event)

    records = {}

    for key, call_events in calls.items():
        initiated = [
            e for e in call_events
            if e["event_type"] == "call.initiated"
        ]

        if not initiated:
            continue

        initiated.sort(key=lambda e: e["occurred_at"])
        initiated_event = initiated[0]

        connected = any(
            e["event_type"] == "call.connected"
            for e in call_events
        )

        failed = any(
            e["event_type"] == "call.telephony_failed"
            for e in call_events
        )

        overrides = [
            e for e in call_events
            if e["event_type"] == "disposition.override"
        ]

        sets = [
            e for e in call_events
            if e["event_type"] == "disposition.set"
        ]

        disposition_events = overrides if overrides else sets
        disposition = None

        if disposition_events:
            latest = max(
                disposition_events,
                key=lambda e: e["occurred_at"]
            )
            payload = json.loads(latest["payload_json"])
            code = payload["disposition_code"]
            disposition = dispositions.get((key[0], code))

            if disposition:
                disposition = {
                    "code": code,
                    **disposition
                }

        records[key] = {
            "workflow_id": key[0],
            "call_id": key[1],
            "lead_id": initiated_event["lead_id"],
            "initiated_at": initiated_event["occurred_at"],
            "connected": connected,
            "telephony_failed": failed,
            "disposition": disposition
        }

    return records



from collections import defaultdict, Counter
from datetime import date

def write_csv_report(path: Path, columns: list, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def generate_reports(
    db_path: Path,
    output_dir: Path,
    schemas: dict,
    dispositions: dict,
    rejections: list,
    all_leads: list,
    field_warnings: dict,
    duplicate_count: int
):
    output_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        events = [
            dict(row) for row in conn.execute("""
                SELECT * FROM interaction_events
                WHERE lead_id IS NOT NULL
            """).fetchall()
        ]

        stored_leads = [
            dict(row) for row in conn.execute(
                "SELECT * FROM leads"
            ).fetchall()
        ]

        quality_rows = conn.execute("""
            SELECT outcome, COUNT(*) AS count
            FROM event_quality
            GROUP BY outcome
        """).fetchall()

    event_quality = {
        row["outcome"]: row["count"] for row in quality_rows
    }

    calls = build_call_records(events, dispositions)

    # Only calls with a linked lead belong in lead-level reports.
    calls = {
        key: call for key, call in calls.items()
        if call["lead_id"] is not None
    }

    leads_by_id = {}
    calls_by_lead = defaultdict(list)

    for row in stored_leads:
        pii = json.loads(decrypt_value(row["pii_encrypted"]))
        public = json.loads(row["data_json"])

        leads_by_id[row["id"]] = {
            "id": row["id"],
            "workflow_id": row["workflow_id"],
            "batch_id": row["batch_id"],
            "external_ref": row["external_ref"],
            "phone": pii["phone"],
            **public
        }

    for call in calls.values():
        calls_by_lead[call["lead_id"]].append(call)

    # Build lead-level report and batch summary.
    lead_report = []
    batch_counts = defaultdict(Counter)

    for lead_id, lead in leads_by_id.items():
        lead_calls = calls_by_lead[lead_id]
        lead_calls.sort(key=lambda call: call["initiated_at"])

        if not lead_calls:
            bucket = "yet_to_reach_out"
        elif any(
            call["disposition"] and call["disposition"]["is_terminal"]
            for call in lead_calls
        ):
            bucket = "completed"
        elif all(call["telephony_failed"] for call in lead_calls):
            bucket = "in_progress_telephony_failed"
        else:
            bucket = "in_progress_dialed"

        batch_key = (lead["workflow_id"], lead["batch_id"])
        batch_counts[batch_key]["total_leads"] += 1
        batch_counts[batch_key][bucket] += 1

        connected_count = sum(call["connected"] for call in lead_calls)

        calls_with_disposition = [
            call for call in lead_calls if call["disposition"]
        ]
        current_disposition = (
            calls_with_disposition[-1]["disposition"]["code"]
            if calls_with_disposition else ""
        )

        ever_success = any(
            call["disposition"] and call["disposition"]["is_success"]
            for call in lead_calls
        )

        phone = lead["phone"]
        masked_phone = "+91******" + phone[-4:] if phone else ""

        lead_report.append({
            "workflow_id": lead["workflow_id"],
            "external_ref": lead["external_ref"],
            "batch_id": lead["batch_id"],
            "phone_masked": masked_phone,
            "bucket": bucket,
            "total_calls": len(lead_calls),
            "connected_calls": connected_count,
            "last_call_at": (
                lead_calls[-1]["initiated_at"] if lead_calls else ""
            ),
            "current_disposition": current_disposition,
            "ever_success": str(ever_success).lower()
        })

    lead_report.sort(
        key=lambda row: (row["workflow_id"], row["external_ref"] or "")
    )

    batch_summary = []
    for (workflow_id, batch_id), counts in batch_counts.items():
        batch_summary.append({
            "workflow_id": workflow_id,
            "batch_id": batch_id,
            "total_leads": counts["total_leads"],
            "yet_to_reach_out": counts["yet_to_reach_out"],
            "in_progress_telephony_failed": counts["in_progress_telephony_failed"],
            "in_progress_dialed": counts["in_progress_dialed"],
            "completed": counts["completed"]
        })

    batch_summary.sort(
        key=lambda row: (row["workflow_id"], row["batch_id"])
    )

    # Build daily overview.
    daily_counts = defaultdict(lambda: {
        "total_calls": 0,
        "connected_calls": 0,
        "success_leads": set()
    })

    for call in calls.values():
        call_date = datetime.fromisoformat(
            call["initiated_at"]
        ).date().isoformat()

        key = (call["workflow_id"], call_date)
        daily_counts[key]["total_calls"] += 1

        if call["connected"]:
            daily_counts[key]["connected_calls"] += 1

        if (
            call["disposition"]
            and call["disposition"]["is_success"]
        ):
            daily_counts[key]["success_leads"].add(call["lead_id"])

    daily_overview = []

    for (workflow_id, call_date), counts in daily_counts.items():
        total = counts["total_calls"]
        connected = counts["connected_calls"]

        daily_overview.append({
            "workflow_id": workflow_id,
            "date": call_date,
            "total_calls": total,
            "connected_calls": connected,
            "connectivity_rate": f"{connected / total:.4f}",
            "success_leads": len(counts["success_leads"])
        })

    daily_overview.sort(
        key=lambda row: (row["workflow_id"], row["date"])
    )

    # Sort rejected rows.
    rejections.sort(
        key=lambda row: (
            row["workflow_id"],
            row["batch_id"],
            row["row_number"]
        )
    )

    # Write the five required outputs.
    write_csv_report(
        output_dir / "batch_summary.csv",
        [
            "workflow_id", "batch_id", "total_leads",
            "yet_to_reach_out", "in_progress_telephony_failed",
            "in_progress_dialed", "completed"
        ],
        batch_summary
    )

    write_csv_report(
        output_dir / "daily_overview.csv",
        [
            "workflow_id", "date", "total_calls",
            "connected_calls", "connectivity_rate", "success_leads"
        ],
        daily_overview
    )

    write_csv_report(
        output_dir / "lead_report.csv",
        [
            "workflow_id", "external_ref", "batch_id",
            "phone_masked", "bucket", "total_calls",
            "connected_calls", "last_call_at",
            "current_disposition", "ever_success"
        ],
        lead_report
    )

    write_csv_report(
        output_dir / "rejections.csv",
        ["workflow_id", "batch_id", "row_number", "reason"],
        rejections
    )

    reason_counts = Counter(
        row["reason"] for row in rejections
    )

    data_quality = {
        "lead_rows_total": len(all_leads) + len(rejections),
        "lead_rows_rejected": len(rejections),
        "rejections_by_reason": dict(reason_counts),
        "duplicate_lead_rows_merged": duplicate_count,
        "field_warnings": field_warnings,
        "events_total": sum(event_quality.values()),
        "malformed_events": event_quality.get("malformed", 0),
        "duplicate_events_dropped": event_quality.get("duplicate", 0),
        "orphan_events": event_quality.get("orphan", 0),
        "unknown_disposition_events": event_quality.get(
            "unknown_disposition", 0
        )
    }

    with (output_dir / "data_quality.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(data_quality, file, indent=2)

    print(f"Reports generated in: {output_dir}")

def main():
    root = Path(__file__).resolve().parent.parent

    data_dir = root / "data"
    schema_dir = root / "assignment-a-data" / "schemas"
    db_path = data_dir / "assignment.db"
    output_dir = root / "reports"

    if not os.environ.get("APP_ENCRYPTION_KEY"):
        raise RuntimeError("APP_ENCRYPTION_KEY is not set.")
    if not os.environ.get("PHONE_HASH_KEY"):
        raise RuntimeError("PHONE_HASH_KEY is not set.")

    schemas = load_all_schemas(schema_dir)

    all_leads, all_rejections, all_warnings = (
        process_all_lead_files(data_dir, schemas)
    )

    unique_leads, duplicate_count = merge_duplicate_leads(all_leads)
    unique_leads = apply_defaults(unique_leads, schemas)

    dispositions = load_dispositions(
        schema_dir / "dispositions.csv"
    )

    create_database(db_path)
    save_leads(db_path, unique_leads, schemas)

    ingest_events(data_dir, db_path, dispositions)
    relink_orphan_events(db_path)

    generate_reports(
        db_path=db_path,
        output_dir=output_dir,
        schemas=schemas,
        dispositions=dispositions,
        rejections=all_rejections,
        all_leads=all_leads,
        field_warnings=all_warnings,
        duplicate_count=duplicate_count
    )


if __name__ == "__main__":
    main()
