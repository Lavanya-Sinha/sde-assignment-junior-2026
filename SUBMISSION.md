# Submission

> Replace everything in _italics_. Be concise: bullet points are fine. We read every word.

## Candidate
- **Name:** _Lavanya Sinha
- **Assignment chosen:** _A (Data)
- **Time spent (honest estimate):** 10 hours

## How to run
```bash
# Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Generate the supplied synthetic dataset
python3 assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

# Configure encryption and hashing keys
export APP_ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export PHONE_HASH_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

# Check Python syntax
python -m compileall -q solution

# Run the pipeline
python solution/main.py

Generated reports are written to reports/, and the SQLite database is created under data/.

The encryption keys must be retained if the existing database is reused. Generating new keys makes previously encrypted values unreadable.
```

## Design
1. Lead ingestion and normalization

The pipeline loads workflow schemas and processes CSV files. Headers are normalized and mapped using the schema field names and aliases. Values are trimmed, normalized, and validated according to their field types.

Invalid rows are recorded in the rejection report with the first validation failure. Optional invalid fields are set to null and recorded as warnings.

2. Deduplication and persistence

Leads are identified using the combination of workflow_id and canonical phone number. Duplicate rows are merged in processing order, with later non-null values overwriting earlier values. Defaults are applied after merging.

Sensitive lead fields are encrypted using Fernet. Phone numbers are represented in the database using keyed HMAC hashes for identity matching rather than storing the canonical phone number as a plain-text lookup key.

3. Event ingestion

JSONL event files are processed line by line. Events are validated, deduplicated using their event IDs, and linked to leads using workflow and normalized phone identity. Override events are linked through call IDs.

Events that cannot be linked are retained as orphaned-event quality records. Malformed, duplicate, and unknown-disposition events are tracked separately.

4. Call reconstruction and reporting

Events are grouped by workflow and call ID to reconstruct calls. Effective dispositions account for overrides, and calls are used to determine each lead's processing bucket.

The pipeline generates five reports: batch summary, daily overview, lead report, rejections, and data quality.

Database schema

| Table | Purpose |
| --- | --- |
| `leads` | Stores workflow identity, phone hash, encrypted PII, non-PII data, external reference, and batch |
| `interaction_events` | Stores deduplicated interaction events and their lead/call relationships |
| `processed_inputs` | Tracks processed event input lines to support repeat ingestion |
| `event_quality` | Tracks event outcomes such as stored, malformed, duplicate, orphaned, and unknown disposition |

## Decisions & assumptions

| Decision | Why | Alternative considered |
| --- | --- | --- |
| SQLite for persistence | Keeps setup simple and avoids requiring a running database server | PostgreSQL |
| Workflow + canonical phone as lead identity | Matches the identity rule implied by the supplied data and schemas | Using external references alone |
| Later non-null values overwrite earlier values during duplicate merging | Preserves the latest available information while avoiding overwriting populated fields with nulls | Keeping only the first row |
| Apply schema defaults after merging | Allows later rows to provide actual values before defaults are applied | Applying defaults to every row before merging |
| Interpret timestamps without timezone information as IST | The reporting requirements use IST and the input includes naive timestamps | Rejecting timestamps without timezone information |
| Latest override takes precedence over disposition sets | An explicit override should supersede the originally assigned disposition | Always using the latest disposition event |
| Keep orphan events in quality tracking | Prevents unlinked events from silently disappearing or affecting lead reports | Dropping orphan events |
| Encrypt raw event lines | Raw event records may contain sensitive information | Store raw event lines in plaintext |
| Ignore unknown disposition codes while counting them | Prevents unrecognized codes from being treated as valid business outcomes | Rejecting the entire event file |

## Failure modes considered
Handled:

Missing required fields and invalid values in lead rows are recorded as rejections.

Invalid optional values become null and are recorded as field warnings.

Blank CSV rows are skipped.

Duplicate lead identities are merged.

Malformed JSONL records are counted and skipped.

Duplicate event IDs are dropped.

Events without a matching lead are tracked as orphaned.

Unknown disposition codes are counted and ignored.

Event ingestion uses event IDs and processed-input tracking to prevent duplicate processing on reruns.

Sensitive lead fields and raw event lines are encrypted before persistence.

Known limitations / not fully handled:

Existing lead identities are currently ignored during database insertion rather than updated during a later incremental ingestion. The current run processes all lead files before ingesting events.

Orphan events are retained, but the solution does not guarantee that every orphan can eventually be resolved.

A comprehensive automated test suite and crash-injection testing have not been implemented.

Recovery from every possible interruption during a multi-stage pipeline run has not been independently verified.

The local smoke test was performed using Python 3.10.12, while the assignment specifies Python 3.11 or later.

## Testing
Testing performed:

Generated the supplied small synthetic dataset using seed 42.

Ran the complete pipeline successfully.

Verified that all five expected reports were generated.

Checked lead acceptance, rejection, and duplicate-merge counts.

Checked event ingestion quality metrics.

Verified that event raw payloads in SQLite are encrypted.

Ran Python syntax compilation successfully.

Testing not performed:

No separate automated unit-test suite was added.

No large-scale dataset benchmark was recorded.

No deliberate process termination (kill -9) or crash-recovery test was performed.

The solution has not yet been independently tested using Python 3.11 or later.

## Results
The pipeline completed successfully against the generated small dataset.

Lead processing:

Total lead rows: 2,057

Rejected rows: 108

Accepted rows: 1,949

Duplicate rows merged: 57

Unique leads after merging: 1,892

Event processing:

Total event lines: 8,745

Malformed events: 8

Duplicate events dropped: 235

Orphan events: 461

Unknown-disposition events: 21

Generated reports:

batch_summary.csv

daily_overview.csv

lead_report.csv

rejections.csv

data_quality.json

One notable result was the presence of 461 orphan events. These were tracked in the data-quality output rather than silently discarded.

Execution time was not measured during the run.

## If I had another day
Add automated unit tests for normalization, validation, deduplication, disposition precedence, and lead-bucket classification.

Improve incremental lead ingestion so later batches can update existing lead records safely.

Add stronger transaction boundaries and test recovery after interrupted runs.

Run the solution using the required Python 3.11+ runtime.

Benchmark the pipeline with the larger supplied dataset and optimize any bottlenecks.

Improve observability with structured logging and clearer ingestion summaries.
