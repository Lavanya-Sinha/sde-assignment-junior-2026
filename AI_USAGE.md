# AI Usage Disclosure

AI tools are allowed. We want to know **how** you used them, because using them well is a
skill. Honest answers are never held against you. Discovering undisclosed use is.

## Tools used
ChatGPT

## What I used them for
I used ChatGPT extensively throughout Assignment A.

I had a tight deadline and limited prior experience with Python. My primary development experience is with JavaScript and full-stack web development, so I used ChatGPT to help me work through an unfamiliar language while completing the assignment.

Specifically, I used it to:

Break down the assignment requirements into smaller implementation steps.

Explain Python syntax, standard-library modules, SQLite operations, and unfamiliar concepts.

Develop the lead ingestion pipeline, including header mapping, field normalization, validation, and duplicate merging.

Implement encryption, phone hashing, database persistence, and event ingestion.

Work through event linking, orphan handling, disposition overrides, call reconstruction, and report generation.

Debug implementation issues and discuss edge cases.

Review and clean up the final main.py file, including removing temporary execution and testing snippets while preserving my existing comments.

Prepare the submission documentation and setup instructions.

AI assistance went beyond explanations and code review: it contributed directly to writing and refining substantial portions of the implementation.

## What I wrote or decided myself
I worked through the assignment requirements and made decisions about how to structure the solution.

My contributions included:

Choosing a pipeline-based approach with SQLite for persistence.

Deciding to identify leads using workflow ID and canonical phone number.

Working through the duplicate-merging behavior and applying defaults after merging.

Deciding how to handle malformed events, duplicate event IDs, orphan events, and unknown dispositions.

Working through the relationship between call events, disposition sets, and overrides.

Choosing to track ingestion quality rather than silently discard problematic records.

Reviewing the implementation and deciding which limitations needed to be documented.

I also ran the pipeline, inspected the generated reports, and checked the database output.

I want to distinguish between making these decisions and independently implementing every line of code. ChatGPT helped substantially with the actual Python implementation.

## Where the AI was wrong or unhelpful
One recurring limitation was that AI-generated code or suggestions sometimes needed to be checked against the actual assignment requirements and the existing implementation.

For example:

Some suggested implementation and documentation details needed correction after comparing them with the actual database schema and code.

The first cleanup discussion did not fully account for the distinction between the database tables created during initialization and the table created later during event ingestion.

Suggestions about testing and submission documentation sometimes introduced additional work that was not explicitly required by the assignment.

I addressed these by checking the actual code, generated reports, and assignment instructions rather than accepting every suggestion as correct.

## How I verified AI-generated code
I did not rely solely on AI's claims that the implementation was correct.

I verified the solution by:

Running the supplied synthetic data generator with seed 42.

Running the complete pipeline locally.

Checking that all five expected reports were generated.

Inspecting the data-quality metrics and checking that lead acceptance, rejection, and duplicate counts reconciled.

Running Python syntax compilation on the cleaned implementation.

Querying the SQLite database to verify that stored raw event payloads were encrypted.

Reviewing the generated reports and database structure against the assignment requirements.

The pipeline completed successfully on the supplied small dataset.

I did not add a separate automated unit-test suite, perform crash-injection testing, or independently verify the solution using Python 3.11 or later. These remain areas for improvement.

I am prepared to discuss the implementation, explain the decisions behind it, and identify areas where I would improve it further.
