# Implementation Progress Tracker

> Last updated: 2026-05-18

---

## Phase Overview

| Phase | Name | Status | Target Week |
|---|---|---|---|
| 1 | Core Infrastructure | Not Started | Week 1 |
| 2 | First Agent (Research) | Not Started | Week 1 |
| 3 | Full Workflow | Not Started | Week 2 |
| 4 | Asset Generation | Not Started | Week 2 |
| 5 | Observability | Not Started | Week 3 |
| 6 | Polish & Optimization | Not Started | Week 3 |

---

## Phase 1 — Core Infrastructure

**Goal:** Working FastAPI app connected to Postgres, Redis, Temporal, and Kafka.

### Tasks
- [ ] Project scaffolding (directory structure, pyproject.toml, Dockerfile)
- [ ] FastAPI app skeleton (main.py, routers, middleware)
- [ ] Docker Compose: postgres, redis, temporal, kafka, zookeeper, minio
- [ ] Database migrations (Alembic): `projects`, `workflow_executions`, `ai_usage`, `assets`, `research_chunks`
- [ ] pgvector extension enabled
- [ ] Temporal SDK integration (worker + client)
- [ ] Kafka producer/consumer base classes
- [ ] Health check endpoints (`GET /health`, `GET /ready`)
- [ ] Basic project CRUD endpoints (no workflow yet)
- [ ] Request validation with Pydantic models
- [ ] Structured JSON logging setup

### Done
*(nothing yet)*

---

## Phase 2 — First Agent (Research)

**Goal:** End-to-end flow: create project → Temporal fires → Research Agent runs → result stored.

### Tasks
- [ ] OpenAI client wrapper with retry + backoff
- [ ] Research Agent prompt template
- [ ] `research_topic` Temporal activity
- [ ] `FilmProductionWorkflow` stub (research only)
- [ ] Temporal worker registered and running
- [ ] `ai_usage` row written after each LLM call
- [ ] Research results stored in `workflow_executions`
- [ ] `GET /api/v1/projects/{id}/status` reflects workflow state
- [ ] Basic progress event published to Kafka

### Done
*(nothing yet)*

---

## Phase 3 — Full Workflow

**Goal:** All agents connected in sequence; error handling and retries working.

### Tasks
- [ ] Script Agent prompt + activity
- [ ] Storyboard Agent prompt + activity
- [ ] Quality Agent validation logic
- [ ] Agent-to-agent data passing through workflow context
- [ ] Progress events for each phase (Kafka → DB update)
- [ ] Retry policy configured per activity
- [ ] Partial failure handling (compensating transactions)
- [ ] `POST /api/v1/projects/{id}/retry` endpoint
- [ ] WebSocket progress stream (`WS /api/v1/projects/{id}/stream`)

### Done
*(nothing yet)*

---

## Phase 4 — Asset Generation

**Goal:** Parallel voiceover, image, and music generation; assets stored in MinIO.

### Tasks
- [ ] ElevenLabs (or TTS) client + `generate_voiceover` activity
- [ ] Stable Diffusion (or mock) client + `generate_images` activity
- [ ] `select_music` activity (library or mock)
- [ ] Parallel execution with `asyncio.gather` in workflow
- [ ] MinIO/S3 upload helper
- [ ] `assets` table rows written per asset
- [ ] `assemble_video` activity (FFmpeg or mock)
- [ ] `GET /api/v1/projects/{id}/download` endpoint

### Done
*(nothing yet)*

---

## Phase 5 — Observability

**Goal:** Full visibility into every workflow execution and LLM call.

### Tasks
- [ ] OpenTelemetry SDK setup (traces + spans)
- [ ] Instrument FastAPI, Temporal activities, Kafka
- [ ] Prometheus metrics exporter
- [ ] Grafana dashboards (workflow duration, error rate, cost)
- [ ] LangSmith integration for LLM traces
- [ ] Cost tracking accurate to ±1% (validate against OpenAI dashboard)
- [ ] `GET /api/v1/projects/{id}/logs` endpoint

### Done
*(nothing yet)*

---

## Phase 6 — Polish & Optimization

**Goal:** Production-ready: caching, RAG, cost optimization, documentation.

### Tasks
- [ ] Redis caching for LLM responses (hash prompt → response)
- [ ] RAG: embed research chunks into pgvector
- [ ] RAG: similarity search context injection for Script/Storyboard agents
- [ ] Circuit breaker for flaky external APIs
- [ ] Rate limiting middleware (per-user, per-project)
- [ ] Anthropic prompt caching enabled
- [ ] Budget limit enforcement (hard stop at project budget)
- [ ] `GET /api/v1/projects/{id}/cost` breakdown endpoint
- [ ] Architecture diagrams (draw.io or Mermaid)
- [ ] README with setup, demo, and design notes

### Done
*(nothing yet)*

---

## Decisions Log

| Date | Decision | Reason |
|---|---|---|
| 2026-05-18 | Use Temporal over Celery | Durable execution, built-in retry, workflow versioning |
| 2026-05-18 | Kafka for events (not just Temporal signals) | Event sourcing, audit trail, independent consumer scaling |
| 2026-05-18 | MinIO for local dev, S3 for prod | Same API surface, no cloud dependency in dev |
| 2026-05-18 | pgvector over dedicated vector DB | Simplicity, same Postgres connection, sufficient for this scale |

---

## Known Issues / Blockers

*(none yet)*

---

## Architecture Diagrams

To be created in Phase 6. Planned diagrams:
1. System context (C4 Level 1)
2. Container diagram (C4 Level 2)
3. Temporal workflow sequence diagram
4. Kafka topic data flow diagram
