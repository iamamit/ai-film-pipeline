# AI Film Production Pipeline

A distributed AI orchestration platform that generates documentary-style videos from a text prompt.

**Input:** `"Create a 10-minute documentary about the Berlin Wall"`  
**Output:** Complete video file — script, voiceover, visuals, music, assembled.

---

## Architecture at a Glance

```
Client
  │
  ▼
FastAPI (API Gateway)
  │  ├── REST endpoints
  │  └── WebSocket (real-time progress)
  │
  ├──► Temporal (Workflow Orchestration)
  │       └── FilmProductionWorkflow
  │             ├── Research Agent
  │             ├── Script Agent
  │             ├── Storyboard Agent
  │             ├── Asset Generation (parallel)
  │             │     ├── Voiceover
  │             │     ├── Images
  │             │     └── Music
  │             └── Video Assembly
  │
  ├──► Kafka (Event Streaming)
  │       ├── film.project.*  (lifecycle events)
  │       ├── film.commands.* (worker commands)
  │       └── film.dlq.*      (dead letter queue)
  │
  └──► Storage
        ├── PostgreSQL  (metadata, costs, status)
        ├── pgvector    (research embeddings)
        ├── Redis       (cache, rate limits)
        └── MinIO/S3    (audio, images, video)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Python 3.11 |
| Orchestration | Temporal |
| Messaging | Kafka |
| Database | PostgreSQL + pgvector |
| Cache | Redis |
| Storage | MinIO (dev) / S3 (prod) |
| LLM Text | OpenAI GPT-4 + Anthropic Claude |
| LLM Voice | ElevenLabs |
| LLM Image | Stable Diffusion API |
| Tracing | OpenTelemetry |
| Metrics | Prometheus + Grafana |
| LLM Observability | LangSmith |
| Runtime | Docker + Docker Compose |

---

## Project Documents

- [PROJECT.md](PROJECT.md) — Full project brief, requirements, schema, workflow definitions
- [PROGRESS.md](PROGRESS.md) — Implementation tracker (phases, tasks, decisions log)

---

## Getting Started

> Setup instructions will be added in Phase 6.

---

## Implementation Status

See [PROGRESS.md](PROGRESS.md) for current phase and task completion.
