# AI Film Production Pipeline — Project Brief

## Project Overview

A distributed AI orchestration platform that generates documentary-style videos from text prompts.

**Input:** `"Create a 10-minute documentary about the Berlin Wall"`

**Output:** Complete video file with AI-generated script, voiceover, visuals, background music, and assembled timeline.

**Core Focus:** Backend engineering and distributed systems — the AI calls are the use case, the system design is what matters.

---

## Functional Requirements

### 1. Project Creation
- User submits topic, duration, tone, style
- System validates input and creates project
- Returns project ID and estimated completion time

### 2. Research Phase
- Gather information about topic using LLM
- Extract key facts, dates, people, events
- Structure research for script generation
- Store research data with embeddings (RAG)

### 3. Script Generation
- Generate documentary narration script
- Structure: intro (10%), body (80%), conclusion (10%)
- Time-aligned to target duration
- Scene breakdown with timestamps

### 4. Storyboard Creation
- Break script into scenes (15–20 second segments)
- Generate visual descriptions for each scene
- Create shot list with camera angles
- Map scenes to script timestamps

### 5. Asset Generation (Parallel)
- Generate voiceover (text-to-speech API)
- Generate images/video clips (Stable Diffusion/similar)
- Select background music (from library or generate)
- All assets tagged with scene/timestamp

### 6. Timeline Assembly
- Combine all assets on timeline
- Sync voiceover with visuals
- Add transitions and effects
- Render final video

### 7. Progress Tracking
- Real-time status updates
- Progress percentage (0–100%)
- Current phase indicator
- ETA for completion
- Error reporting

### 8. Project Management
- List user's projects
- Get project status
- Download completed video
- Retry failed steps
- Cancel in-progress projects

---

## Non-Functional Requirements

| Requirement | Target |
|---|---|
| Async Processing | Workflows 10–30 min, must be non-blocking |
| Reliability | Graceful AI API failure handling with retries |
| Scalability | 100+ concurrent projects |
| Observability | Full tracing and metrics |
| Cost Control | Track and limit AI API spend per project |
| Fault Tolerance | Recover from crashes, resume workflows |
| Performance | Sub-second API responses |

---

## Technical Architecture

### Core Components

| Component | Technology | Purpose |
|---|---|---|
| API Gateway | FastAPI | REST endpoints, WebSocket, auth, rate limiting |
| Workflow Orchestration | Temporal | Multi-step workflows, state persistence, retries |
| Event Streaming | Kafka | Decouple steps, event sourcing, DLQ |
| Worker Pool | Python workers | Per-agent workers, horizontal scaling |
| Metadata DB | PostgreSQL | Project data, status, costs |
| Vector DB | pgvector | Research embeddings for RAG |
| Cache | Redis | Rate limiting, temp data, caching |
| Object Storage | S3/MinIO | Generated assets (audio, images, videos) |
| LLM Text | OpenAI GPT-4 / Claude | Research, script generation |
| LLM Voice | ElevenLabs | Voiceover generation |
| LLM Images | Stable Diffusion | Scene image generation |
| Tracing | OpenTelemetry | Distributed tracing |
| Metrics | Prometheus + Grafana | Dashboards and alerting |
| LLM Tracing | LangSmith | LLM-specific observability |

---

## Database Schema

```sql
-- Projects
CREATE TABLE projects (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    topic TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    tone VARCHAR(50),
    status VARCHAR(50),        -- pending, processing, completed, failed
    progress INTEGER DEFAULT 0, -- 0-100
    current_phase VARCHAR(100),
    estimated_completion TIMESTAMP,
    total_cost DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    error_message TEXT
);

-- Workflow executions (for debugging)
CREATE TABLE workflow_executions (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    workflow_id VARCHAR(255),  -- Temporal workflow ID
    phase VARCHAR(100),
    status VARCHAR(50),
    input JSONB,
    output JSONB,
    error TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- AI API usage (cost tracking)
CREATE TABLE ai_usage (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    provider VARCHAR(50),      -- openai, anthropic, etc
    model VARCHAR(100),
    operation VARCHAR(100),    -- research, script, etc
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost DECIMAL(10,4),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Generated assets
CREATE TABLE assets (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    type VARCHAR(50),          -- script, voiceover, image, video
    scene_number INTEGER,
    storage_url TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Research embeddings (pgvector)
CREATE TABLE research_chunks (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    content TEXT,
    embedding vector(1536),    -- OpenAI embedding dimension
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ON research_chunks USING ivfflat (embedding vector_cosine_ops);
```

---

## Temporal Workflow Definition

```python
@workflow.defn
class FilmProductionWorkflow:
    @workflow.run
    async def run(self, project_id: str, topic: str, preferences: dict) -> dict:
        # Phase 1: Research (5-10 min)
        research_data = await workflow.execute_activity(
            research_topic,
            args=[topic, preferences],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        # Phase 2: Script Generation (5-10 min)
        script_data = await workflow.execute_activity(
            generate_script,
            args=[topic, research_data, preferences],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        # Phase 3: Storyboard (3-5 min)
        storyboard_data = await workflow.execute_activity(
            create_storyboard,
            args=[script_data],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        # Phase 4: Asset Generation (Parallel, 10-20 min)
        voice_task = workflow.execute_activity(
            generate_voiceover,
            args=[script_data],
            start_to_close_timeout=timedelta(minutes=15)
        )
        images_task = workflow.execute_activity(
            generate_images,
            args=[storyboard_data],
            start_to_close_timeout=timedelta(minutes=20)
        )
        music_task = workflow.execute_activity(
            select_music,
            args=[preferences],
            start_to_close_timeout=timedelta(minutes=5)
        )

        voice_url, images_urls, music_url = await asyncio.gather(
            voice_task, images_task, music_task
        )

        # Phase 5: Assembly (2-5 min)
        final_video = await workflow.execute_activity(
            assemble_video,
            args=[script_data, voice_url, images_urls, music_url],
            start_to_close_timeout=timedelta(minutes=10)
        )

        return {
            "status": "completed",
            "video_url": final_video,
            "project_id": project_id
        }
```

---

## API Endpoints

```
# Project Management
POST   /api/v1/projects               Create new project
GET    /api/v1/projects               List user's projects
GET    /api/v1/projects/{id}          Get project details
DELETE /api/v1/projects/{id}          Cancel project
GET    /api/v1/projects/{id}/download Download video

# Progress Tracking
GET    /api/v1/projects/{id}/status   Current status
WS     /api/v1/projects/{id}/stream   Real-time WebSocket updates

# Cost Management
GET    /api/v1/projects/{id}/cost     Cost breakdown
GET    /api/v1/usage                  User's total usage

# Admin / Debug
GET    /api/v1/projects/{id}/logs     Execution logs
POST   /api/v1/projects/{id}/retry    Retry failed step
```

---

## Kafka Topics

```
# Events (published by workers)
film.project.created
film.project.started
film.research.completed
film.script.completed
film.storyboard.completed
film.assets.completed
film.assembly.completed
film.project.completed
film.project.failed

# Commands (consumed by workers)
film.commands.research
film.commands.script
film.commands.storyboard
film.commands.generate_voice
film.commands.generate_images
film.commands.assemble

# Dead Letter Queue
film.dlq.failed_events
```

---

## Multi-Agent System

```
Research Agent  →  Script Agent  →  Storyboard Agent
      ↓                ↓                   ↓
  Quality Agent    Quality Agent       Quality Agent
```

**Research Agent** — Gather and synthesize information  
**Script Agent** — Generate narration script using research context  
**Storyboard Agent** — Create visual descriptions from script scenes  
**Quality Agent** — Validate each agent's output before passing forward

---

## AI/LLM Technical Requirements

### LLM Integration
- GPT-4 for complex reasoning (script, research)
- GPT-3.5-turbo for simple tasks (cost optimization)
- Claude as fallback/alternative
- Function calling for structured outputs
- Streaming for real-time updates

### Prompt Engineering
- Structured prompts with clear instructions
- Few-shot learning examples
- Chain-of-thought reasoning
- Context management between agents
- Dynamic prompt templates

### Error Handling
- Retry with exponential backoff (up to 3 attempts)
- Fallback to cheaper model on rate limits
- Cache responses to avoid re-generation
- Circuit breaker for flaky APIs
- Graceful degradation (skip optional steps)

### Cost Management
- Estimate token count before API calls
- Set budget limits per project
- Track actual costs in `ai_usage` table
- Alert on budget threshold
- Use Anthropic prompt caching

### Output Validation
- Validate JSON schema for structured outputs
- Check content moderation
- Verify length constraints
- Quality scoring (coherence, relevance)
- Regenerate on validation failure

### RAG Implementation
- Embed research data with OpenAI embeddings (1536-dim)
- Store in pgvector
- Retrieve relevant context for each agent
- Update embeddings on new research

---

## Key Design Questions

1. How do you handle AI API rate limits?
2. How do you retry failed steps without re-executing successful ones?
3. How do you track costs accurately?
4. How do you ensure exactly-once execution?
5. How do you handle partial failures (script succeeds, images fail)?
6. How do you scale workers independently?
7. How do you debug a failed workflow?
8. How do you implement backpressure?
9. How do you cache AI responses?
10. How do you version workflows for backward compatibility?

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11+ |
| Orchestration | Temporal |
| Messaging | Kafka |
| Primary DB | PostgreSQL |
| Vector DB | pgvector |
| Cache | Redis |
| Object Storage | S3 / MinIO |
| LLM (text) | OpenAI GPT-4, Anthropic Claude |
| LLM (voice) | ElevenLabs |
| LLM (image) | Stable Diffusion API |
| Tracing | OpenTelemetry |
| Metrics | Prometheus + Grafana |
| LLM Observability | LangSmith |
| Deployment | Docker, Docker Compose |
