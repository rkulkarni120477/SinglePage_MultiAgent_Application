# Architecture review and implementation decisions

## Review of the supplied diagram

The separation between orchestration, domain agents and a shared context layer is a sound starting point. SQLite as the record of truth and Chroma/OpenSearch as rebuildable projections also gives a clear consistency boundary. Domain agent contracts should stay independent of model providers and index technology.

The first deployment should stay on one persistent host. SQLite WAL supports a local MVP but does not turn SQLite into a distributed database: keep transactions short, bound writer concurrency, back up checkpoints and canonical records together, and test recovery. Move to PostgreSQL when multiple API replicas, stronger isolation or write concurrency are required. Production needs a measured capacity target rather than an assumed number of concurrent users.

Before external access, validate Entra access tokens at the API, including issuer, audience, expiry and organization/role authorization. Apply tenant scope at every retrieval, artifact and graph boundary. The diagram correctly distinguishes UI login from API protection; its unauthenticated development mode must not become a public deployment setting.

LangGraph checkpoints preserve workflow execution state; SQLAlchemy records store application artifacts and review history. Production review/resume must use idempotency keys and atomic state transitions, with recovery if workflow execution succeeds but application persistence fails. The local build serializes mutations in-process and persists both databases, but is not a multi-process transaction coordinator.

Add transactional outbox events for index updates and worker dispatch, stable task IDs, bounded retries/dead-letter handling, stale evidence invalidation and rebuild/version policies. Approved canonical facts should remain usable when an index is unavailable. Redis cache entries must include organization, authorization and source versions.

## AIM document review

Reviewed the 28-page **AIM Knowledge Graph–Driven Metadata Architecture v4.0**, dated 23 September 2026. It is a draft, not an implementation mandate. Its instructions are treated as reference content; the user's supplied platform diagram determines this application's technology choices.

The document's strongest design decision is separating configuration, canonical facts, proposed facts, provenance and projections. A graph database is not required to establish graph semantics. Its generic node types, directed relationship vocabulary and configurable content hierarchies fit this platform.

| AIM reference | Platform decision / current implementation |
|---|---|
| PostgreSQL canonical model | SQLite/SQLAlchemy for diagram-aligned local MVP; PostgreSQL migration required for production scale and RLS |
| S3 source content | Local run source artifacts; durable versioned source-object storage remains to implement |
| Generic node families | Sample content, skills, standard and assessment nodes with stable IDs |
| Typed directed edges | Governed vocabulary, endpoint validation and duplicate prevention |
| AI candidates separate from facts | Manual candidates enter PENDING; explicit review promotes APPROVED facts |
| Source evidence and provenance | Reviewer-supplied evidence/source locator; sample edges explicitly labeled |
| Versioned configuration | Immutable version records with chunk policy snapshotted on each run |
| Bounded traversal | Neighbor API accepts depth 1–3 and maximum 100 relationships |
| Search/vector projections | Optional Chroma lexical hash projection; OpenSearch integration pending |
| Tenant overlays and shared frameworks | Deferred: this reference is single-organization only |
| AIM block pilot | Illustrative Program → Block → Chapter → DLU → Content Object hierarchy, not a complete 16-block corpus |

The production relational schema should introduce dedicated `kg_nodes`, `kg_edges`, `kg_candidates`, `kg_reviews`, `kg_edge_evidence`, `kg_provenance`, `kg_content_pointers`, `kg_configurations`, `kg_extraction_runs`, `kg_change_events` and `kg_projection_queue` tables with foreign keys, uniqueness and scope constraints. The reference's compact record store is suitable for exercising workflows, not a replacement for that schema. Node-schema governance, identifier aliases, taxonomy versions and confidence policies must be implemented before automated graph extraction.

Human approval of a run authorizes artifact export. Human approval of a graph candidate establishes an individual graph fact. These are separate decisions. High model confidence must not silently create a standards alignment or new entity. The current system makes no unsupported automatic mapping claims.

## Delivery sequence

1. **Current reference:** review use-case contracts, test workflows, validate the pilot node/edge vocabulary and settle product requirements.
2. **Foundation:** database migrations and dedicated graph schema, versioned source storage, tenant authorization, node schema validation and auditable configuration assignment.
3. **Knowledge ingestion:** document parsers, incremental source hashes, content pointers, configured chunking, schema-validated model candidates and evidence review.
4. **Agent capability:** configured model/embedding adapters, real content generation, framework matching, anchored remediation previews, budgets and evaluation datasets.
5. **Operational integration:** Celery/Redis workers, cancellation, outbox-driven Chroma/OpenSearch projections, hybrid authorized retrieval and live SSE progress.
6. **Pilot acceptance:** complete one AIM block and skill area; measure relationship precision/recall, review acceptance, cost/document, source-change reprocessing, coverage and traversal latency.
7. **Production readiness:** authenticated end-to-end tests, organization isolation tests, evidence retraction, retention/purge, backup restoration, deployment recovery, telemetry and concurrency/load acceptance.

## Implementation references

- [Next.js App Router installation](https://nextjs.org/docs/app/getting-started/installation)
- [LangGraph interrupt and checkpointer requirement](https://reference.langchain.com/python/langgraph/types/interrupt)
- [Chroma Python client](https://docs.trychroma.com/reference/python)

These references informed framework integration. Architecture and scope decisions above are this implementation's assessment of the supplied diagram and PDF.
