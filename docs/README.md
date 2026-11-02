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

Redis and OpenSearch are provisioned as optional local services but are **not wired** into workflow execution. Celery workers, hybrid ranking, outbox/retry processing, Entra/MSAL authentication, additional model providers, document uploads/OCR, cancellation, budgets, telemetry, immutable audit storage, migrations and full lifecycle/retraction/purge are production backlog. Runs execute synchronously with bounded local inputs; the event endpoint emits a snapshot, not live worker progress. Do not expose this reference build as a hosted production platform.

See [ARCHITECTURE.md](ARCHITECTURE.md) for review decisions, the AIM comparison and delivery plan.

