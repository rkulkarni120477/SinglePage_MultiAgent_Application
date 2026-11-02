# Academian Multi-Agent Education Platform

A runnable local reference implementation of the supplied architecture. The Next.js single-page workbench includes ten sample use cases across all seven modules, agent input/output contracts, editable source briefs, LangGraph workflow execution, durable human review, JSON export, run history and a governed knowledge graph pilot.

## Run locally

Requires Node.js 20.9+ and Python 3.11+. Run from this directory.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

In a second terminal:

```powershell
npm ci
npm run dev
```

Open http://localhost:3010. API documentation: http://127.0.0.1:8010/docs. Next.js proxies `/api/v1` to FastAPI; set `API_URL` for another backend origin. Configure Amazon Bedrock in `backend/.env` before generating drafts (see below). The API is intentionally unauthenticated and must remain loopback-only. UI login alone would not protect these APIs.

## Use the application

1. Choose a use case. Read its description, inputs, outputs and agent contracts.
2. Select **Configure workflow**, edit the source brief, then **Run workflow**.
3. Inspect the actual artifacts. Approve or reject the paused workflow; approved runs can be downloaded as JSON.
4. Open **Knowledge graph** to inspect the illustrative Program → Block → Chapter → DLU → Content Object hierarchy and relationship evidence.
5. Propose a typed relationship with evidence. Approve it in the candidate queue to make it available to retrieval.
6. Reopen saved workflow artifacts from **Run history**.

Runtime records and LangGraph checkpoints persist in `data/`. `DATA_DIR` can override this directory. Run history survives restarts. This build uses one local organization and a fixed local reviewer identity; it does not provide tenant isolation or authenticated authorization.

Backend settings are loaded automatically from `backend/.env`, regardless of the working directory. Existing process environment variables take precedence. Set `CHROMA_HOST` and `CHROMA_PORT` to enable the optional Chroma adapter, or uncomment `DATA_DIR` to choose an absolute storage directory. Restart FastAPI after editing settings. The `.env` file is ignored by Git; `backend/.env.example` provides the shareable template. The default provider is Amazon Bedrock. Configure:

```dotenv
MODEL_PROVIDER=bedrock
AWS_REGION=us-east-1
AWS_BEARER_TOKEN_BEDROCK=your-local-api-key
BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
```

Alternatively, omit the bearer token and use the standard AWS SDK credential chain (including `AWS_PROFILE`). The identity needs permission to invoke the selected Bedrock model. Keep credentials in the ignored `.env` file. Nova Lite is the default; override the model ID with a Converse-compatible model supporting forced tool use (Amazon Nova or Anthropic Claude). Cross-region profiles can be specified explicitly if required by your model/account.

Each selected specialist makes one Bedrock Converse request before human review. The retrieval-only use case makes one context-answer request. Structured tool results are validated with Pydantic; failed, refused, truncated or invalid model responses fail the request without template fallback. Source chunking, lexical graph retrieval and HTML checks remain deterministic and are supplemented by model-generated recommendations. Approving resumes the saved graph and unlocks export without repeating generation. Saved artifacts report model ID, request IDs, token usage and completed calls. Cost is shown as unavailable because the API does not return dollar charges; consult AWS billing.

Use `MODEL_PROVIDER=deterministic` explicitly for an offline demo. Tests select this mode and mock Bedrock for generation coverage. Old saved runs retain their original outputs; start a new workflow to generate model drafts.

## Generate a deliverable FAA course

For an aviation electrical-maintenance workflow containing a content blueprint, approve the source workflow, then select **Generate FAA course** beneath its artifacts. This works with existing saved workflow JSON, including older template runs that contain the original brief.

The backend downloads the official FAA-S-ACS-1 ACS and FAA-H-8083-30B General handbook from fixed FAA URLs and caches them under `data/reference_sources/`. It extracts selected electrical requirements and relevant handbook pages, preserving source URLs, edition, download time, PDF page numbers, printed page labels and SHA-256 hashes. The initial handbook download is approximately 93 MB; subsequent builds reuse the cached sources and extracts. Cached PDFs are retained until manually refreshed; source editions are recorded rather than silently claimed to be the latest.

Bedrock generates a course plan, assessments, observable scoring rubrics, proposed alignment rows and three full lessons. Full-course authoring defaults to `amazon.nova-pro-v1:0`; configure `BEDROCK_COURSE_MODEL_ID` to override it. The short workflow specialists continue using `BEDROCK_MODEL_ID`. Schema checks reject incomplete output, invented ACS codes, broken objective/lesson/assessment references, unknown citation pages, missing safety-critical rubric criteria and short lesson content. A schema-invalid plan can receive up to two model repair requests, and an invalid lesson can receive one; successful course usage totals include those requests. Generation still fails if validation cannot be satisfied, with no template fallback. These checks do not establish factual correctness: an instructor must review the source-linked full preview, practical activities, answer keys and mappings. The scope is selected aviation electrical fundamentals, not all A&P standards or FAA approval. Missing selected mappings are listed explicitly.

The new course has its own review state. Choose **Review full lessons, answers & rubrics**, review it, then **Approve course** and **Download course ZIP**. The ZIP includes:

- `index.html`: learner lessons, activities, questions and scoring expectations.
- `instructor.html`: the course plus suggested answers and instructor guidance.
- `alignment-matrix.csv` and `assessment-rubrics.csv`: editable review tables.
- `course.json` and `workflow.json`: generated course and original workflow records.
- `sources/manifest.json` and `sources/extracted-pages.json`: provenance and downloaded source excerpts. Full FAA PDFs remain available through their official links.

The ZIP includes instructor answers; distribute learner material separately. It is a portable browser-readable course package, not a SCORM package or LMS integration. Rejection or regeneration does not alter the approved source workflow. Reopen the workflow in Run history to retrieve its latest saved course draft.

API: `POST /api/v1/runs/{id}/course`, `GET /api/v1/runs/{id}/course`, `POST /api/v1/courses/{id}/review`, `GET /api/v1/courses/{id}/preview`, and approval-gated `GET /api/v1/courses/{id}/export`.

## Verification

```powershell
python -m unittest backend.test_platform -v
npm run build
```

Backend tests use a separate temporary database. They exercise all ten workflow branches, durable review interrupts, export gates, replay prevention, candidate promotion, duplicate detection, traversal limits, versioned configuration and HTML findings.

## Implementation scope

Implemented: Next.js/React UI, FastAPI/Pydantic contracts, SQLAlchemy/SQLite WAL persistence, LangGraph SQLite checkpointer and interrupts, LangChain Runnable retrieval, source hashing and configurable chunking, controlled sample skill matching, instructional templates, basic HTML checks, typed graph proposals, evidence, local audit events and manual candidate approval.

Model generation is connected through Amazon Bedrock; model drafts and new mappings require review. Standard alignment and framework crosswalks require reviewer mappings. Accessibility checks do not establish WCAG compliance. Retrieval uses approved graph labels and relations; it does not answer from unavailable source content. Ingestion returns chunks inside run artifacts; it does not yet persist full document/content-pointer entities or automatically extract graph candidates. Graph proposals are created manually in the graph workspace.

Optional Chroma adapter: `docker compose --profile infrastructure up -d`, set `CHROMA_HOST=127.0.0.1`, restart FastAPI, then POST `/api/v1/projections/rebuild` and GET `/api/v1/projections/search?q=safety`. This projection uses explicit deterministic lexical hash vectors; replace them with a configured embedding model for semantic retrieval. Chroma is derived, never canonical. Infrastructure containers and this adapter require separate integration validation on your Docker environment.

Redis and OpenSearch are provisioned as optional local services but are **not wired** into workflow execution. Celery workers, hybrid ranking, outbox/retry processing, Entra/MSAL authentication, additional model providers, document uploads/OCR, cancellation, budgets, telemetry, immutable audit storage, migrations and full lifecycle/retraction/purge are production backlog. Runs and course builds execute synchronously with bounded local inputs; the Next.js API proxy permits up to 15 minutes for these local generation requests; the event endpoint emits a snapshot, not live worker progress. Do not expose this reference build as a hosted production platform.

See [ARCHITECTURE.md](ARCHITECTURE.md) for review decisions, the AIM comparison and delivery plan.

