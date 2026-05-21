# AI Film Production Pipeline — Senior Engineer Interview Q&A

> **How to use this document:** Every question is followed by a thorough answer written as if you are speaking in an interview — confident, specific, and grounded in the actual codebase. Follow-up questions drill into the same topic from a different angle. File names and function names from the real project are cited where relevant.

---

## Table of Contents

1. [System Design & Architecture](#1-system-design--architecture)
2. [FastAPI](#2-fastapi)
3. [SQLAlchemy 2.0 Async](#3-sqlalchemy-20-async)
4. [Alembic](#4-alembic)
5. [pgvector & Embeddings](#5-pgvector--embeddings)
6. [Temporal Workflow Orchestration](#6-temporal-workflow-orchestration)
7. [Kafka](#7-kafka)
8. [Redis](#8-redis)
9. [Groq API & LLMs](#9-groq-api--llms)
10. [Docker & Docker Compose](#10-docker--docker-compose)
11. [React Frontend](#11-react-frontend)
12. [General Engineering Questions](#12-general-engineering-questions)

---

## 1. System Design & Architecture

### Q: Give a high-level walkthrough of the AI Film Production Pipeline architecture.

**Answer:** The system is a distributed pipeline that takes a documentary topic from a user and orchestrates AI agents — research, scripting, storyboarding, asset generation, and video assembly — across multiple specialized services. At the core is a FastAPI backend that exposes a REST API under `/api/v1`. When a user creates a project, the API persists the record to a PostgreSQL 16 database (with the pgvector extension for storing semantic embeddings), then fires off a Temporal workflow in a non-blocking fire-and-forget call. A Temporal Worker process — running as a separate Python process via `film/temporal/worker.py` — picks up that workflow from the `film-production` task queue and orchestrates each production phase as a discrete Activity. Activities do the heavy lifting: calling the Groq LLM API to research the topic, generating sentence-transformer embeddings and storing them as 384-dimensional vectors in pgvector, and updating project progress in the database. A Kafka broker (KRaft mode) provides an event bus for lifecycle events so downstream services can react to phase completions without tight coupling. Redis serves as an async singleton cache for session data and rate limiting. MinIO provides S3-compatible object storage for generated assets. The React 19 frontend polls the API every 3–4 seconds via TanStack Query to show live pipeline progress. The entire infrastructure is wired together with Docker Compose, which launches eight services: `app-db`, `temporal-db`, `redis`, `temporal`, `temporal-ui`, `kafka`, `minio`, and `minio-init`.

**Follow-up: Why did you choose a distributed architecture instead of a simple monolith for this project?**

The core reason is that the film production pipeline is inherently asynchronous and long-running. Research, scripting, and video assembly can each take minutes or hours. If you handle all of this inside a single HTTP request, you'll hit timeouts and you lose the ability to resume on failure. By pulling orchestration into Temporal and execution into a Worker, the HTTP request returns immediately (201 Created) while the actual work continues independently. Additionally, the pipeline is designed to grow: future phases will add specialized workers for voice synthesis, image generation, and video assembly — each of which benefits from independent scaling. A monolith would force you to scale everything together even if the bottleneck is only the GPU-bound image generation stage.

**Follow-up: What's the difference between Temporal and Kafka in this design — don't they overlap?**

They solve different problems. Temporal is the authoritative orchestrator: it keeps a durable event log of every workflow step, handles retries with configurable backoff, and guarantees that the workflow completes exactly once even if the worker crashes and restarts. Temporal is about *control flow*. Kafka is a broadcast event bus: once a phase completes, the worker publishes a `film.research.completed` event to Kafka so that any number of downstream subscribers (analytics dashboards, notification services, future specialized workers) can react without knowing about the orchestrator. Kafka is about *fan-out and decoupling*. If you only had Kafka, you would lose workflow state management and retry logic. If you only had Temporal, you would lose the ability to have multiple independent consumers react to events without coupling them to the workflow.

**Follow-up: What trade-offs did you consciously make in the current design?**

Several deliberate trade-offs were made. First, the API currently uses a simple `X-User-ID` header instead of JWT tokens — this is pragmatic for Phase 1 but means there is no token expiry or signature verification. Second, the Kafka producer is optional at startup (`logger.warning` on failure, not a crash), meaning the app can run without Kafka in development — this speeds up local development at the cost of potentially missing events in a degraded state. Third, `expire_on_commit=False` is set on the SQLAlchemy session factory, which means loaded ORM objects remain accessible after a commit; this is essential for async contexts but it does mean stale data can be served if the object is reused across multiple requests without re-fetching. Fourth, the Temporal client is cached as a global singleton, which simplifies code but means tests must explicitly override it via `set_temporal_client()` in `film/temporal/client.py`.

---

### Q: How does a project flow from the HTTP request all the way to the database being updated?

**Answer:** The flow has five distinct stages. Stage one: the React frontend calls `POST /api/v1/projects` with a JSON body and the `X-User-ID` header. Stage two: FastAPI's dependency injection resolves `CurrentUser` (validates the UUID from the header) and `DbSession` (yields an `AsyncSession` from the `async_sessionmaker`). Stage three: the route handler in `film/api/v1/projects.py` creates a `Project` ORM object, calls `db.add(project)` and `await db.commit()`, then immediately calls `temporal.start_workflow()`. The workflow ID is deterministic — `f"film-{project.id}"` — so if the same project is accidentally submitted twice, Temporal will return a `WorkflowAlreadyStarted` error rather than running it twice. Stage four: the Worker process, which is subscribed to the `film-production` task queue, dequeues the `FilmProductionWorkflow` and begins executing it. It calls `workflow.execute_activity(research_topic, ...)` which dispatches to the `research_topic` activity. Stage five: inside the activity, a fresh `AsyncSessionFactory()` session is opened, the Groq API is called, the text is chunked and embedded via `sentence-transformers`, and `ResearchChunk` rows are inserted into PostgreSQL with their 384-dimensional embedding vectors. The project's `status`, `progress`, and `current_phase` fields are updated at each milestone (5% when research starts, 20% when it completes). The frontend's TanStack Query polling picks up the updated status on its next tick.

**Follow-up: Why does the activity open its own database session instead of sharing the one from the API request?**

Activities run in the Worker process, which is a completely separate Python process from the FastAPI server. There is no shared memory, no shared connection pool, no shared anything. The `AsyncSession` from the API request is created in the API process and is completely inaccessible to the worker. Each activity must establish its own database connection from scratch, which is why `AsyncSessionFactory()` is imported and used directly inside `research_topic`. This is actually a feature — it enforces strong process boundaries and means each activity is independently deployable.

**Follow-up: What happens if Temporal is down when the user submits a project?**

The code in `film/api/v1/projects.py` wraps the `temporal.start_workflow()` call in a try/except block and logs a warning instead of raising an exception. The project record is still written to the database with `status="pending"`. This is an intentional design decision for Phase 1: the API call succeeds and the user gets a 201 response. The project will remain in `pending` state indefinitely until Temporal comes back online and a workflow is manually triggered, or until an operator-run backfill job picks it up. In production, you would want a scheduled job or a startup reconciliation process that finds `pending` projects with no associated workflow and re-submits them.

---

## 2. FastAPI

### Q: Why did you choose FastAPI over Flask or Django for this project?

**Answer:** There are four primary reasons. First, FastAPI is natively async — it is built on Starlette and uses Python's `asyncio` throughout, which means every route, dependency, and middleware can be a coroutine. This is non-negotiable for this project because we need to await database calls (`await db.execute(...)`), await Temporal client calls (`await temporal.start_workflow(...)`), and await Redis pings, all within the same request lifecycle without blocking the event loop. Flask's sync model would require either running everything in threads or bolting on an async extension. Django is sync-first with async support bolted on, and the ORM is not designed for true async operation. Second, FastAPI's Pydantic integration gives us automatic request validation and serialization for free — the `ProjectCreate` model in `film/schemas/project.py` enforces `min_length=1` on topic and `ge=1, le=60` on `duration_minutes` without any manual validation code. Third, FastAPI generates a full OpenAPI spec automatically, and we customized it with `openapi_tags`, `swagger_ui_parameters`, and the `APIKeyHeader` security scheme so the Swagger UI has an Authorize button for `X-User-ID` out of the box. Fourth, FastAPI's dependency injection system via `Depends` is extremely composable — `CurrentUser` and `DbSession` in `film/api/deps.py` are type aliases that can be dropped into any route signature, keeping routes clean and dependencies testable.

**Follow-up: How does FastAPI's dependency injection work? Walk me through the CurrentUser dependency.**

In `film/api/deps.py`, we define `_user_id_scheme = APIKeyHeader(name="X-User-ID", ...)` which is a security scheme object that FastAPI knows to show in the Swagger Authorize UI. The `get_current_user` function is an async function decorated with nothing special — it's just a regular coroutine. It takes `x_user_id: Annotated[str | None, Security(_user_id_scheme)] = None` as a parameter; FastAPI sees the `Security()` wrapper and knows to extract the `X-User-ID` header value and pass it as `x_user_id`. Inside the function, we validate that it exists and is a valid UUID, then return the `uuid.UUID` object. Finally, we define `CurrentUser = Annotated[uuid.UUID, Depends(get_current_user)]` — this is a type alias. When a route handler declares `user_id: CurrentUser` as a parameter, FastAPI resolves it by calling `get_current_user`, which in turn resolves its own `Security` dependency. The entire dependency graph is resolved before the route handler body runs.

**Follow-up: What is the async lifespan pattern and why use it instead of @app.on_event?**

The `@asynccontextmanager` lifespan pattern, used in `film/main.py`, is the modern FastAPI way to run startup and shutdown logic. It is preferred over the deprecated `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators because it uses a single async context manager, which means startup and shutdown are guaranteed to be paired — you can't forget to write the shutdown handler because it is the code after the `yield`. The `yield` is the point at which the application runs; everything before it is startup and everything after it is shutdown. In our `lifespan` function, we start in this order: verify the database is reachable, initialize the Redis singleton, optionally connect to Temporal, optionally start the Kafka producer. On shutdown (after the `yield`), we stop Kafka, close Redis, and dispose of the SQLAlchemy engine. Crucially, Temporal and Kafka startup failures are caught and logged as warnings — they don't crash the app — making the system resilient to partial infrastructure outages.

**Follow-up: How did you customize the OpenAPI/Swagger UI?**

In `create_app()` in `film/main.py`, the `FastAPI()` constructor takes several customization arguments. `title` and `description` appear at the top of the Swagger UI, and the description uses markdown, including an instruction telling developers to add the `X-User-ID` header. `openapi_tags` provides an ordered list of tag groups with descriptions, which groups the `/health` and `/ready` endpoints under "health" and the project endpoints under "projects". `swagger_ui_parameters={"persistAuthorization": True}` tells the Swagger UI to remember the authorization token across page refreshes — otherwise, every time you reload the docs page you have to click Authorize again and re-enter your UUID. The `APIKeyHeader` scheme in `deps.py` registers the security scheme in the OpenAPI spec, which is what makes the Authorize button appear.

**Follow-up: How does APIRouter work and why do you have two levels of routing?**

`APIRouter` is FastAPI's way of organizing routes into modules. In `film/api/v1/projects.py`, we create `router = APIRouter(prefix="/projects", tags=["projects"])` — every route registered on this router automatically gets `/projects` prepended. In `film/api/v1/router.py`, we create `api_v1_router = APIRouter(prefix="/api/v1")` and include the projects router inside it. In `film/main.py`, we include `api_v1_router`. The final URL for the create endpoint is the concatenation of all three prefixes: `` + `/api/v1` + `/projects` + `` (since the route decorator is `@router.post("")`), resulting in `POST /api/v1/projects`. This layered approach means adding a new version (v2) is as simple as creating a new `api_v2_router` without touching the v1 routes.

---

### Q: How do Pydantic models differ from ORM models, and how do you bridge them?

**Answer:** ORM models in `film/db/models.py` are SQLAlchemy `Mapped` classes that define the database schema — they know about columns, foreign keys, indexes, and relationships. They are Python objects that SQLAlchemy tracks internally and can flush to the database. Pydantic models in `film/schemas/project.py` are pure data-validation and serialization containers. They know nothing about the database; they define what shape of data is valid at the API boundary. The bridge between them is `model_config = ConfigDict(from_attributes=True)` on the response schemas like `ProjectResponse`. This tells Pydantic to read values from object attributes (which is how ORM instances work) instead of from dictionary keys. When a route returns a `Project` ORM instance and the route is annotated with `response_model=ProjectResponse`, FastAPI calls `ProjectResponse.model_validate(project_orm_instance)`, which reads `project_orm_instance.id`, `project_orm_instance.topic`, etc., and produces a validated Pydantic object that is then serialized to JSON. This means you never accidentally leak internal ORM fields (like lazy-loaded relationships) to the client.

**Follow-up: What happens if you forget from_attributes=True on a response schema?**

Pydantic will raise a `ValidationError` at runtime with a message like "value is not a valid dict" because by default Pydantic expects a dictionary input, not an object with attributes. You would see a 500 Internal Server Error in production because our global exception handler catches unhandled exceptions and returns `{"detail": "Internal server error"}`. The actual `ValidationError` would appear in the structlog output. This is a common gotcha when migrating from Pydantic v1 (where `orm_mode = True` was the equivalent setting) to Pydantic v2 (where `from_attributes = True` inside `ConfigDict` is the new syntax).

---

## 3. SQLAlchemy 2.0 Async

### Q: Why async SQLAlchemy and what does that mean in practice?

**Answer:** Traditional SQLAlchemy uses blocking I/O — when you call `session.execute(query)`, the calling thread blocks until the database responds. In an async FastAPI application running on a single-threaded event loop, any blocking call stalls the entire server — no other requests can be processed while one request is waiting for a database response. Async SQLAlchemy, introduced properly in version 2.0, uses `asyncpg` as the database driver (instead of `psycopg2`). `asyncpg` implements the PostgreSQL protocol over non-blocking sockets and is fully coroutine-native. The SQLAlchemy session becomes `AsyncSession`, and every operation that touches the network is awaited: `await db.execute(...)`, `await db.commit()`, `await db.refresh(obj)`. Under the hood, the event loop is free to handle other coroutines while a database query is in flight. In our `film/db/session.py`, we create an `async_sessionmaker(engine, expire_on_commit=False)` which produces `AsyncSession` objects. The engine is a `create_async_engine` with `pool_pre_ping=True`, `pool_size=10`, and `max_overflow=20`, meaning we maintain a pool of 10 persistent connections and can burst to 30.

**Follow-up: What does expire_on_commit=False do and why is it important in async?**

By default, SQLAlchemy marks all attributes of an ORM object as "expired" after a `commit()`, which means the next time you access an attribute, SQLAlchemy will issue a lazy SELECT to refresh it. In a synchronous context this is transparent. In an async context, attribute access is synchronous code — if you try to read `project.id` after a commit, SQLAlchemy needs to issue a `SELECT` query to refresh the object, but there is no async context to await that query. This causes a `MissingGreenlet` error or `DetachedInstanceError`. Setting `expire_on_commit=False` tells SQLAlchemy to leave the Python object's attributes as-is after a commit, so you can safely read them without triggering a lazy load. This is essential in async SQLAlchemy. The trade-off is that the object may reflect stale data if another process modified the same row after your commit — but for our use case (returning the just-committed object to the API response), the data is correct by definition.

**Follow-up: Explain the Mapped and mapped_column syntax in models.py.**

The `Mapped[T]` annotation syntax is SQLAlchemy 2.0's new way of defining column types. Instead of `Column(UUID, primary_key=True)`, you write `id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)`. The `Mapped[uuid.UUID]` tells SQLAlchemy (and your IDE and mypy) that reading `project.id` will return a `uuid.UUID`. The `mapped_column(...)` is where you specify the actual database column configuration — dialect-specific type, constraints, defaults, indexes. This approach has full type inference: the ORM model is essentially a typed Python dataclass that SQLAlchemy understands how to persist. It replaces the old declarative style where you wrote `id = Column(UUID(...))` with no type information for the IDE.

**Follow-up: Why is the metadata attribute reserved and how was it fixed?**

SQLAlchemy's `DeclarativeBase` class already defines a class-level attribute called `metadata` which is a `MetaData` object used internally to track all table definitions. If you define a column called `metadata` on an ORM model, you silently shadow the class-level `MetaData` object, which breaks Alembic's migration detection and can cause subtle bugs. This is why the `Asset` and `ResearchChunk` models in `film/db/models.py` use the pattern `meta: Mapped[dict | None] = mapped_column("metadata", JSON)`. The Python attribute is named `meta` (safe, no conflict), and `mapped_column("metadata", ...)` specifies that the actual database column name is `metadata`. This way, code accesses the field as `asset.meta` while the database column is named `metadata`.

**Follow-up: How does connection pooling work in this setup?**

The `create_async_engine` in `film/db/session.py` configures `pool_size=10` (the minimum number of persistent connections to maintain), `max_overflow=20` (additional connections that can be created above `pool_size` under load, but are closed when returned to the pool), and `pool_pre_ping=True` (before lending a connection from the pool, issue a lightweight `SELECT 1` to verify it's still alive — important after a database restart or network hiccup). This means under steady load we maintain 10 connections, and under burst load we can open up to 30. The `async_sessionmaker` wraps each session in an `AsyncContextManager` that automatically checks the connection back into the pool when the session is closed, ensuring connections are not leaked.

---

### Q: Walk me through the SQLAlchemy query patterns used in the projects router.

**Answer:** Three distinct query patterns are used. The first is `db.get(Model, primary_key)` — used in the activities: `await db.get(Project, project_id)`. This is a shorthand for fetching by primary key and uses the session's identity map cache before hitting the database. The second is the full `select()` statement: in `get_project`, we do `await db.execute(select(Project).where(Project.id == project_id, Project.user_id == user_id))` and then call `.scalar_one_or_none()` on the result. `scalar_one_or_none()` returns the single ORM object if found, or `None` if no rows matched — it raises an exception if more than one row matches, which is the right behavior for a primary-key lookup. The third pattern is used in `list_projects`: we call `.scalars().all()` which returns a list of all matching ORM objects. The `scalars()` call unwraps the row tuples (since `select(Project)` returns rows of `(Project,)` tuples by default) into plain `Project` objects, and `.all()` materializes the generator into a list.

---

## 4. Alembic

### Q: What is Alembic and why does the project use it?

**Answer:** Alembic is SQLAlchemy's database migration tool. It tracks the version history of your database schema as a chain of migration scripts, each with an `upgrade()` function (apply the change) and a `downgrade()` function (revert the change). Without Alembic, if you add a column to your ORM model, you still need to run `ALTER TABLE` manually on every environment. With Alembic, you write a migration script once and run `alembic upgrade head` on every environment to bring it to the latest schema version. The `alembic.ini` file at the project root tells Alembic where to find the migration scripts (the `alembic/` directory) and the `alembic/env.py` is the Python bridge that reads our `Settings.database_url`, imports all ORM models (via `import film.db.models`), and exposes `Base.metadata` so Alembic knows the target schema state. The `alembic/env.py` also handles the async engine correctly — it wraps the migration execution in `asyncio.run(run_migrations_online())` since Alembic itself is synchronous.

**Follow-up: Why did you hand-write the migrations instead of using alembic revision --autogenerate?**

Autogenerate works by comparing the current database state against `Base.metadata` and generating the diff. For a clean start it works fine, but there are several cases where it fails or generates incorrect SQL. Most importantly, autogenerate does not know about custom PostgreSQL extensions like `pgvector` — it cannot generate `CREATE EXTENSION IF NOT EXISTS vector`. It also does not automatically create custom index types like `IVFFlat` with `vector_cosine_ops`. By hand-writing the migrations, we have full control over the SQL: we can write `CREATE EXTENSION IF NOT EXISTS vector`, define the `Vector(384)` column type, and create the IVFFlat index with the correct operator class in a single migration script. Hand-written migrations are also easier to review in code review because they show exactly what SQL will run.

**Follow-up: What is the down_revision chain and why does it matter?**

Every Alembic migration file has two important attributes: `revision` (its own unique ID, like `"a1b2c3d4e5f6"`) and `down_revision` (the ID of the migration it depends on). This forms a linked list — a chain from the initial migration to the latest one. When you run `alembic upgrade head`, Alembic reads the chain from your current database version (stored in the `alembic_version` table) to `head` and applies each migration in order. When you run `alembic downgrade -1`, it applies the `downgrade()` function of the most recent migration and updates the `alembic_version` table. If two developers create migrations simultaneously with the same `down_revision`, Alembic will detect a branch in the chain and refuse to upgrade, forcing you to merge the migrations. This is how Alembic prevents schema conflicts.

---

## 5. pgvector & Embeddings

### Q: What is pgvector and why does this project use it?

**Answer:** pgvector is a PostgreSQL extension that adds a native `vector` column type and the ability to perform approximate nearest-neighbor similarity searches on vectors directly in SQL. It means PostgreSQL can store and efficiently query high-dimensional float arrays — in our case, 384-dimensional sentence embeddings. The extension is enabled by using the `pgvector/pgvector:pg16` Docker image, which comes with the extension pre-compiled. In the ORM model `film/db/models.py`, the `ResearchChunk.embedding` field is defined as `mapped_column(Vector(384), nullable=True)` using the `pgvector.sqlalchemy.Vector` type, which handles the serialization of Python lists of floats to the PostgreSQL wire format. The `IVFFlat` index on that column allows the database to perform approximate cosine-similarity searches over millions of embeddings in milliseconds rather than doing a brute-force scan.

**Follow-up: What are vector embeddings and why do you need them?**

A vector embedding is a dense numerical representation of a piece of text (or image, or audio) that encodes its semantic meaning. The `all-MiniLM-L6-v2` model from `sentence-transformers` takes a string and outputs a list of 384 floats. Two semantically similar strings (e.g., "The Berlin Wall fell in 1989" and "Germany was reunified after the Wall came down") will have embeddings that are close together in 384-dimensional space, measured by cosine similarity. Two semantically dissimilar strings will have embeddings far apart. We need embeddings for RAG — Retrieval Augmented Generation. When the scripting phase runs in a future iteration, rather than feeding the entire research text (which may be too long for the LLM's context window) into the script-writing prompt, we embed the script query and do a cosine similarity search in pgvector to retrieve only the most relevant research chunks. This makes the LLM call much more focused and efficient.

**Follow-up: Why specifically all-MiniLM-L6-v2 and why 384 dimensions?**

`all-MiniLM-L6-v2` is a sentence-transformer model that is a distilled version of a larger BERT model. "MiniLM" means it has been significantly compressed (L6 = 6 transformer layers). It outputs 384-dimensional embeddings, which is small enough to be fast to compute (on CPU, without a GPU) and small enough to store efficiently in PostgreSQL, while still providing high-quality semantic similarity. For this project, which runs on a laptop or a modest VM in development, a GPU-heavy model like `all-mpnet-base-v2` (768 dims) would add significant startup time and memory overhead with marginal quality improvement for our use case. The 384-dim model can embed a paragraph in under 100ms on CPU. The model is loaded lazily in `film/activities/research.py` via `_get_embed_model()` with module-level caching, so it is only loaded once per worker process lifecycle.

**Follow-up: How does the IVFFlat index work and what does vector_cosine_ops mean?**

IVFFlat stands for Inverted File with Flat quantization. It is an approximate nearest-neighbor (ANN) index. During index build time, it clusters the vectors into `lists` clusters (configurable) using k-means. At query time, it finds the nearest `probes` cluster centroids and then does a brute-force search within only those clusters. This means instead of comparing a query vector against all N vectors in the table (O(N)), it compares against approximately N/lists vectors. `vector_cosine_ops` specifies that the distance metric is cosine distance (1 - cosine_similarity). Cosine distance is ideal for text embeddings because it measures the angle between vectors rather than their magnitude, making it invariant to text length. The SQL for the similarity query would look like: `SELECT content FROM research_chunks ORDER BY embedding <=> query_vector LIMIT 10` where `<=>` is the cosine distance operator provided by pgvector.

**Follow-up: How exactly will RAG be used in the scripting phase?**

In the scripting activity (Phase 2), the workflow will call a `write_script` activity. That activity will construct a query like "what were the key causes of the Berlin Wall's fall?" and embed it using `all-MiniLM-L6-v2`. It will then run a pgvector cosine similarity search against `research_chunks` filtered by `project_id`, retrieving the top-K (e.g., 10) most semantically relevant chunks. These chunks are injected into the scripting prompt as context: "Using the following research excerpts: [chunk 1] [chunk 2]..., write a narration script for a 10-minute dramatic documentary about the Berlin Wall." This keeps the LLM prompt focused, reduces token costs, and ensures the script is grounded in factual research rather than the model's potentially outdated training data.

---

## 6. Temporal Workflow Orchestration

### Q: What is Temporal and why use it instead of raw queues or Celery?

**Answer:** Temporal is a durable workflow orchestration platform. It runs workflows as persistent state machines that survive process crashes, network partitions, and infrastructure restarts. The key differentiator from raw message queues (Kafka, RabbitMQ) or Celery is that Temporal maintains the full execution history of every workflow as an event log stored in PostgreSQL. If the Worker process crashes halfway through the `research_topic` activity, Temporal detects the heartbeat timeout, reschedules the activity on any available worker, and the workflow continues from where it left off — without any manual checkpointing code. Celery with Redis or RabbitMQ is stateless about workflow progress: it retries individual tasks but does not know about multi-step workflows. If a Celery task that is step 3 of 10 fails after completing steps 1 and 2, you either retry the whole chain from the beginning or write complex state management code yourself. Temporal's event sourcing approach makes multi-step, long-running workflows with retries, timeouts, and cancellations first-class concepts.

**Follow-up: What is the distinction between a Workflow and an Activity in Temporal?**

A Workflow is the orchestrator: it defines the control flow — which activities to run, in what order, with what retry policies and timeouts. Critically, Workflow code must be deterministic: given the same event history, it must produce the same sequence of decisions. This is why you cannot call `datetime.now()`, `random.random()`, or make direct network calls inside a Workflow. In `film/workflows/production.py`, `FilmProductionWorkflow.run()` only calls `workflow.execute_activity()` — it does no I/O itself. An Activity is where the actual work happens: I/O, API calls, database writes, embedding generation. Activities can be non-deterministic and can fail and be retried. In `film/activities/research.py`, `research_topic()` calls the Groq API, runs the sentence-transformer model, and writes to PostgreSQL — all the messy real-world operations are contained here. The separation enforces a clean architecture: workflows are testable as pure state machines, activities are independently retryable units of work.

**Follow-up: Why does the workflow file use imports_passed_through?**

The `with workflow.unsafe.imports_passed_through():` block in `film/workflows/production.py` is one of the most common points of confusion with Temporal's Python SDK. Temporal's workflow sandbox intercepts module imports to enforce determinism — it blocks imports of modules that are known to perform I/O or non-deterministic operations. `structlog` imports `os` and does file I/O to detect terminal types, which the sandbox blocks. `sentence_transformers` and `groq` also fail inside the sandbox. By wrapping the activity imports in `imports_passed_through()`, we tell the sandbox: "these modules are imported in workflow code only to get type hints and the activity function reference — they will not actually be called from within the workflow code itself." The actual execution of these modules happens inside activities, which run outside the sandbox in a normal Python environment.

**Follow-up: What does "workflow determinism" mean and why does Temporal require it?**

Temporal replays a workflow's event history to reconstruct its state whenever a worker reconnects, upgrades, or the workflow resumes after a sleep. During replay, the workflow code runs again from the beginning, but instead of actually executing activities, Temporal feeds it the recorded results from the history. For this replay to work correctly, the code must make the same sequence of `execute_activity` calls in the same order every time. If you called `random.choice(activities)`, the replay might schedule a different activity, creating a mismatch with the recorded history and causing a non-determinism error. Temporal's sandbox proactively blocks imports of modules that are commonly misused to introduce non-determinism (`datetime`, `random`, `os`, etc.) and provides deterministic alternatives — for example, you can get the current time inside a workflow via `workflow.now()` which returns the recorded timestamp from the history, not the wall clock.

**Follow-up: How does Temporal guarantee exactly-once execution?**

Exactly-once execution is achieved through a combination of mechanisms. First, workflow IDs are unique — in `film/api/v1/projects.py`, we set `id=f"film-{project.id}"`. If `start_workflow` is called twice with the same ID, Temporal returns a `WorkflowAlreadyStartedError` instead of starting a second instance. Second, activity execution is tracked in the event history: once an activity completes, its result is recorded. During replay, that result is returned from the history without re-executing the activity. Third, for activities that are retried after a failure, idempotency must be implemented by the developer — Temporal will retry the activity, so the activity code must handle being called multiple times with the same input and produce the same result. In our `mark_completed` activity, calling it twice just sets `status="completed"` twice, which is idempotent because the second call is a no-op in terms of observable state.

**Follow-up: Explain the retry policy used in the workflow.**

In `film/workflows/production.py`, we define `RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), maximum_interval=timedelta(minutes=2), maximum_attempts=3)`. This means: if an activity fails, wait 5 seconds before the first retry. If it fails again, use exponential backoff (Temporal doubles the interval by default) with a cap of 2 minutes. After 3 total attempts (1 original + 2 retries), stop retrying and mark the activity as failed, which causes the workflow to fail. The `start_to_close_timeout=timedelta(minutes=5)` on the research activity is the maximum wall-clock time allowed for a single attempt — if the Groq API hangs for 5 minutes, Temporal cancels that attempt and triggers a retry. This combination ensures transient failures (network blips, API rate limits) are handled automatically without manual intervention.

**Follow-up: How do you cancel a workflow?**

From the API, the `cancel_project` route in `film/api/v1/projects.py` does this: `handle = temporal.get_workflow_handle(f"film-{project_id}")` followed by `await handle.cancel()`. `get_workflow_handle()` constructs a handle using the deterministic workflow ID without needing to query Temporal for the actual run ID. `cancel()` sends a cancellation request to the Temporal server, which delivers a `CancelledError` to the currently running activity. Activities should listen for this and clean up. In the Temporal UI at `http://localhost:8080`, you can also cancel workflows manually by finding the workflow execution and clicking the "Request Cancellation" button. The Temporal UI also shows the full event history, the current state, input/output of each activity, and any errors that occurred.

---

### Q: What is the Task Queue concept in Temporal?

**Answer:** A Task Queue is a named virtual queue in Temporal that acts as the dispatch mechanism between the Temporal server and Workers. When a workflow is started with `task_queue="film-production"`, the Temporal server places workflow task dispatches on the `film-production` queue. Workers that are connected to the same queue poll it for tasks. In `film/temporal/worker.py`, the Worker is created with `task_queue=settings.temporal_task_queue` and registered with `workflows=[FilmProductionWorkflow]` and `activities=[research_topic, mark_completed]`. The Worker polls Temporal continuously; when a task arrives, it dispatches to the registered handler. Multiple Workers can be connected to the same Task Queue simultaneously — Temporal will distribute tasks across them, providing horizontal scaling. You can use different Task Queues to route different types of work to different Worker types (e.g., a `gpu-workers` queue for image generation tasks that need GPU resources).

---

## 7. Kafka

### Q: What is Kafka and why does this project include it?

**Answer:** Kafka is a distributed, partitioned, replicated commit log that functions as a high-throughput message broker. In this project, Kafka serves as the event bus for lifecycle notifications. When a production phase completes, a worker publishes an event to a topic like `film.research.completed`. Any number of downstream subscribers — a notification service, an analytics pipeline, a cost-tracking aggregator, a future video assembly worker — can independently consume these events without the producer needing to know about them. This decoupling is the core value proposition. Without Kafka, if you wanted to notify four different services about a completed research phase, you would either call each service directly (tight coupling, any failure breaks the pipeline) or poll the database repeatedly (inefficient, adds load). Kafka provides a persistent, ordered, replayable event log that consumers can process at their own pace. Events are defined in `film/kafka/topics.py` with a clear naming convention: lifecycle events (`film.project.created`, `film.research.completed`) and command events (`film.commands.research`).

**Follow-up: What is KRaft mode and why is it significant?**

KRaft (Kafka Raft) is Kafka's native consensus protocol that replaces ZooKeeper for cluster metadata management. Historically, Kafka required ZooKeeper as a separate service to manage broker metadata, leader election, and configuration. ZooKeeper is a Java service with its own operational overhead — separate JVM process, separate storage, separate monitoring. KRaft removes this dependency by having Kafka manage its own metadata internally using the Raft consensus algorithm (the same algorithm used by etcd and Consul). In our `docker-compose.yml`, the single Kafka container runs with `KAFKA_PROCESS_ROLES: broker,controller` — it is both the broker (handles client connections and topic data) and the controller (manages cluster metadata). The `CLUSTER_ID: 4L6g3nShT-eMCtK--X86sw` is a base64-encoded UUID that must be set before the first startup and never changed, because it is used to identify the cluster in the KRaft metadata log. KRaft mode simplifies operations significantly, especially for development.

**Follow-up: Explain the FilmProducer and FilmConsumer base class design.**

`FilmProducer` in `film/kafka/producer.py` is a concrete class that wraps `aiokafka.AIOKafkaProducer`. It is initialized with a JSON serializer (`value_serializer=lambda v: json.dumps(v, default=str).encode()`), which means any dict can be published as a JSON message. The `default=str` argument handles non-serializable types like `datetime` and `UUID` by converting them to strings. The `publish()` method uses `send_and_wait()` which blocks until the broker acknowledges the message — providing at-least-once delivery guarantees. `FilmConsumer` in `film/kafka/consumer.py` is an abstract base class with a template method pattern. Subclasses implement `handle(msg: ConsumerRecord) -> None`. The base class handles startup, the async message loop (`async for msg in self._consumer`), error logging (including a TODO for a Dead Letter Queue), and shutdown. The DLQ topic `film.dlq.failed_events` is defined in `topics.py` for messages that repeatedly fail processing.

**Follow-up: Why use Kafka alongside Temporal — isn't that redundant?**

No, they are complementary. Temporal is an orchestrator that manages the execution of a specific workflow instance — it knows about `workflow-abc123` and its internal state. Kafka is a broadcast bus for events that happened — it does not know or care about workflow instances. The key distinction is directionality and coupling: Temporal is pull-based (workers poll for tasks they are registered to handle), Kafka is push-based (producers write events, any number of consumers can subscribe independently). A concrete example: when `mark_completed` finishes, the Temporal workflow is done. But we might also want to: (1) send the user an email, (2) update a cost dashboard, (3) trigger a thumbnail generation job. If these are driven by Temporal, we'd have to add them to the `FilmProductionWorkflow` code, coupling them tightly. If we publish `film.project.completed` to Kafka, each of these services subscribes independently and the workflow code doesn't change.

---

## 8. Redis

### Q: What role does Redis play in this project and how is it initialized?

**Answer:** In the current Phase 1 implementation, Redis serves as a fast key-value store that can be used for session data, rate limiting, and caching frequently-accessed data. The architecture is designed for future phases where Redis will cache project status responses (avoiding repeated DB hits for the polling frontend), store distributed locks to prevent duplicate workflow submissions, and hold rate-limit counters for the Groq API calls. Redis is initialized in the `lifespan` function in `film/main.py` using `aioredis.from_url(settings.redis_url, decode_responses=True)` and stored in the `state.redis_client` module-level variable. `decode_responses=True` means all values returned from Redis are automatically decoded from bytes to Python strings. The client is initialized once at application startup and reused for the entire lifetime of the process — a singleton pattern. On shutdown, `await state.redis_client.aclose()` closes the connection pool.

**Follow-up: Why store the Redis client in a module-level variable in state.py rather than using a dependency?**

The Redis client is a connection pool manager, not a per-request resource. Unlike a database session (which should be opened per-request, used, and closed), the Redis connection pool should be opened once and shared across all requests. Making it a `Depends()` dependency would be misleading — it suggests per-request lifecycle. Instead, it is stored in `film/state.py` as a module-level variable (`redis_client: "Redis | None" = None`) and set during lifespan startup. Routes or services that need Redis import `from film import state` and use `state.redis_client`. The `TYPE_CHECKING` guard and string annotations in `state.py` prevent circular imports while still providing type hints for IDEs. In tests, this pattern makes it easy to inject a mock: the `conftest.py` fixture sets `state.redis_client = AsyncMock()` before each test.

**Follow-up: How does async Redis differ from sync Redis?**

The `redis-py` library has both a synchronous client (`redis.Redis`) and an async client (`redis.asyncio.Redis`, formerly `aioredis`). The async client uses `asyncio` internally and its methods are coroutines: `await state.redis_client.ping()`, `await state.redis_client.get("key")`. This is essential in an async FastAPI application — if you called the synchronous `redis.Redis.ping()` inside a route handler, it would block the event loop for the duration of the network round-trip. The async client releases control back to the event loop while waiting for the Redis server to respond, allowing other requests to be processed concurrently. The `redis[asyncio]` package (listed in `pyproject.toml`) installs both the sync and async clients.

---

## 9. Groq API & LLMs

### Q: What is Groq and why did you choose it over OpenAI?

**Answer:** Groq is an AI inference company that runs large language models on custom hardware called LPUs (Language Processing Units). The key advantage for this project is the free tier: Groq provides generous rate limits for free at `api.groq.com` — enough for development and moderate production use. OpenAI's API requires payment from the first token, which creates friction for open-source or portfolio projects. Groq's `llama-3.3-70b-versatile` model is a Meta LLaMA 3.3 model with 70 billion parameters, which provides GPT-4-class quality for document-style tasks like research synthesis and scriptwriting. Another major advantage is speed: Groq's LPUs can generate tokens significantly faster than GPU-based inference, which matters for interactive workflows. The `groq` Python package in `pyproject.toml` provides an `AsyncGroq` client with an API that is wire-compatible with the OpenAI Python SDK — the `chat.completions.create()` call with the `messages`, `model`, `temperature`, and `max_tokens` parameters is identical.

**Follow-up: What does "OpenAI-compatible API" mean in practice?**

Both Groq and OpenAI implement the same REST API schema, originally defined by OpenAI. The `/chat/completions` endpoint accepts the same JSON body structure: `{"model": "...", "messages": [{"role": "user", "content": "..."}], "temperature": 0.7, "max_tokens": 4096}`. This means you can use the `openai` Python package to call Groq by just changing the `base_url` to `"https://api.groq.com/openai/v1"`. We use the Groq-specific `groq` package which does this configuration for you. The practical implication is that switching from Groq to OpenAI (or any other OpenAI-compatible provider like Together AI, Fireworks AI, or a self-hosted Ollama instance) requires changing only the `api_key` and `model` name in `film/core/config.py` — no other code changes.

**Follow-up: Walk me through what happens when research_topic calls the Groq API.**

In `film/activities/research.py`, we instantiate `AsyncGroq(api_key=settings.groq_api_key)` inside the activity function (not at module level) to avoid holding a persistent connection during idle periods. The prompt is constructed using Python format strings with the `topic`, `duration`, and `tone` from `ResearchInput`. We call `await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.7, max_tokens=4096)`. The `temperature=0.7` parameter controls randomness — 0.0 is fully deterministic, 1.0 is maximum creativity; 0.7 is a good balance for factual research. `max_tokens=4096` caps the response length. The response object's `response.usage` attribute contains `prompt_tokens` and `completion_tokens`, which we record in the `AIUsage` table for future cost tracking. The `response.choices[0].message.content` is the text, which we then split into ~600-character paragraph chunks for embedding storage.

---

## 10. Docker & Docker Compose

### Q: Why Docker Compose for development and what services does it run?

**Answer:** Docker Compose eliminates the "works on my machine" problem by defining the entire infrastructure stack in a single `docker-compose.yml` file that any developer can reproduce with `docker compose up`. The project has eight services: `app-db` (PostgreSQL 16 with pgvector, the application database), `temporal-db` (a separate plain PostgreSQL 16 instance used exclusively by the Temporal server to store its event history), `redis` (Redis 7, for caching and rate limiting), `temporal` (the Temporal server itself, using the `auto-setup` image that automatically initializes its schema against `temporal-db`), `temporal-ui` (the Temporal web UI at port 8080), `kafka` (Apache Kafka in KRaft mode), `minio` (S3-compatible object storage for film assets), and `minio-init` (a one-shot `minio/mc` container that creates the `film-assets` bucket). Each service has a named volume for data persistence, so restarting the stack does not wipe data. Health checks on `app-db`, `temporal-db`, `redis`, and `minio` ensure dependent services wait for them to be ready before starting.

**Follow-up: Why is app-db mapped to port 5434 instead of the default 5432?**

Both `app-db` (the application database) and `temporal-db` (Temporal's internal database) are PostgreSQL instances running inside Docker containers. Both containers expose port 5432 internally. If we mapped both to port 5432 on the host machine, there would be a port conflict. The convention used here is: `temporal-db` maps to host port 5433 (`"5433:5432"`), and `app-db` maps to host port 5434 (`"5434:5432"`). This allows a developer to use any PostgreSQL GUI tool (TablePlus, pgAdmin, DBeaver) to connect to the application database on `localhost:5434` while Temporal's internal database is on `localhost:5433`. The `database_url` in `.env.example` uses the host port 5434 for external connections: `postgresql+asyncpg://film:film@localhost:5434/film`. Inside the Docker network, services refer to `app-db:5432`.

**Follow-up: What is a one-shot container and how does minio-init work?**

A one-shot container is a Docker container that runs a task and exits rather than staying running as a persistent service. `minio-init` uses the `minio/mc` (MinIO Client) image with `restart: "no"` to prevent Docker from restarting it after it exits. It `depends_on: minio: condition: service_healthy` so it waits for MinIO to be fully ready before running. The `entrypoint` is a shell script that: (1) sets up an alias pointing `local` to the MinIO server, (2) creates the `film-assets` bucket with `mc mb --ignore-existing` (the `--ignore-existing` flag makes this idempotent — it doesn't fail if the bucket already exists), (3) prints "bucket ready" and exits. The key insight is that `docker compose up` will run this container every time you start the stack, but because of `--ignore-existing`, it's safe to run repeatedly.

**Follow-up: What is the CLUSTER_ID in the Kafka configuration and what happens if it changes?**

The `CLUSTER_ID: 4L6g3nShT-eMCtK--X86sw` in the Kafka KRaft configuration is a base64-encoded UUID that uniquely identifies the Kafka cluster. In KRaft mode, this ID is written into the Kafka data directory on first startup as part of the metadata log. If you change the `CLUSTER_ID` in `docker-compose.yml` without deleting the `kafka_data` volume, Kafka will refuse to start because the ID in the config doesn't match the ID stored on disk. Conversely, if you delete the `kafka_data` volume, all Kafka data (topics, messages, offsets) is lost. The ID must be stable and consistent across all nodes in a cluster. For development, the value is hardcoded in `docker-compose.yml` and committed to version control, which is fine because the data is ephemeral anyway. In production, this would be managed through secrets management.

**Follow-up: Why does the Temporal service use a separate PostgreSQL instance instead of sharing app-db?**

Temporal's internal schema is managed entirely by Temporal — it creates dozens of tables with its own naming conventions and migration history. Running Temporal's schema in the same database as the application would create confusion and risk: a `make migrate` running application migrations against Temporal's tables could cause irreparable damage. More practically, Temporal's data access patterns are very different from the application's — it does many small, high-frequency writes for workflow events, while the application does larger, lower-frequency queries. Keeping them separate allows independent scaling, separate backup schedules, and clear operational ownership.

---

## 11. React Frontend

### Q: Why TanStack Query and what polling strategy does the project use?

**Answer:** TanStack Query (formerly React Query) is a server state management library that handles fetching, caching, background refetching, and synchronization between the server and the UI. The alternative — managing fetch state manually with `useState` and `useEffect` — quickly becomes messy: you need to track `loading`, `error`, and `data` states yourself, handle race conditions, implement deduplication of identical requests, and write cleanup logic. TanStack Query gives all of this for free with a `useQuery` hook. The polling strategy in this project uses `refetchInterval` — in `Dashboard.tsx`, `refetchInterval: 4_000` means TanStack Query will re-fetch the projects list every 4 seconds. In `ProjectDetail.tsx`, `refetchInterval: 3_000` polls the individual project every 3 seconds. This is a simple and effective approach for showing live pipeline progress. The downside is that it creates constant API traffic even for completed projects, but for a Phase 1 MVP this is perfectly acceptable. A future optimization would be to conditionally set `refetchInterval: false` when a project is in a terminal state (`completed`, `failed`, `cancelled`).

**Follow-up: How does useMutation work and how is it used for project creation?**

`useMutation` is TanStack Query's hook for write operations (POST, DELETE, PATCH). Unlike `useQuery`, it does not run automatically — it returns a `mutate` function that you call explicitly. In `CreateProjectModal.tsx`, the mutation is defined as `const create = useMutation({ mutationFn: api.projects.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ['projects'] }); onClose(); }, onError: (err: Error) => setError(err.message) })`. `mutationFn` is the async function that performs the API call. `onSuccess` is called when the API returns successfully — here, we invalidate the `['projects']` query key, which tells TanStack Query to immediately re-fetch the projects list so the new project appears in the dashboard. `onError` handles failure by setting a local error state that renders an error message in the form. The `create.isPending` boolean is used to disable the submit button and show a spinner while the mutation is in flight, preventing double-submission.

**Follow-up: How does QueryClient and QueryClientProvider work?**

`QueryClient` is the central store that TanStack Query uses to hold cached query results, manage background refetch timers, and track mutation states. You create one instance and pass it to `QueryClientProvider` which makes it available to all components in the React tree via React's Context API. In `App.tsx`, `const qc = new QueryClient()` creates the client at module level (important — you don't want to create it inside the component function or it would be recreated on every render). `<QueryClientProvider client={qc}>` wraps the entire app. In `ProjectDetail.tsx`, `const qc = useQueryClient()` retrieves the same `QueryClient` instance from context, allowing the cancel mutation's `onSuccess` handler to imperatively invalidate queries: `qc.invalidateQueries({ queryKey: ['project', id] })`.

**Follow-up: How does the Vite proxy work and why is it needed?**

In `frontend/vite.config.ts`, the dev server is configured with a proxy: `/api` routes are forwarded to `http://localhost:8000`, and `/health` and `/ready` routes are also forwarded. During development, the React app runs on `http://localhost:3000` and the FastAPI backend runs on `http://localhost:8000`. Without the proxy, all API calls from the browser would go to `localhost:3000` (the same origin as the frontend), but FastAPI is on port 8000. Direct cross-origin calls would require CORS preflight on every request and would be blocked by the browser if CORS isn't properly configured. The Vite dev proxy intercepts calls to `/api/...` and transparently forwards them to the backend, making the browser think all traffic is same-origin. In production, an Nginx reverse proxy or a load balancer would perform this same role.

**Follow-up: Describe the dark theme approach with Tailwind CSS.**

The project uses Tailwind's `slate` color palette for the dark theme throughout. The background is `bg-slate-950` (the darkest shade), cards are `bg-slate-900`, borders are `border-slate-800`, primary text is `text-slate-100`, and secondary text is `text-slate-400` or `text-slate-500`. This gradient of gray tones creates depth without explicit light/dark mode switching — the app is always dark. Interactive elements use `bg-indigo-600` with `hover:bg-indigo-500` for primary actions and semantic colors for status: `text-emerald-400` for completed, `text-blue-400` for active, `text-red-400` for failed. The `tailwind.config.js` extends the default theme with a `pulse-slow` animation for loading states. Rather than using Tailwind's dark mode variant (`dark:`), the design commits fully to dark by using dark colors as the base — simpler and consistent.

---

## 12. General Engineering Questions

### Q: How would you scale this system to handle hundreds of concurrent film productions?

**Answer:** Scaling happens at several layers. First, the FastAPI application tier: since it is a stateless async server (aside from the Redis/Kafka singletons which are already external services), you can run multiple instances behind a load balancer like Nginx or AWS ALB. The `pool_size=10, max_overflow=20` pool in SQLAlchemy means each instance can maintain up to 30 database connections, so with 5 instances you'd have 150 connections — PostgreSQL can handle hundreds of connections natively, and PgBouncer can extend that further. Second, the Worker tier: Temporal Workers are stateless pollers — you simply launch more Worker processes (or Kubernetes pods) connected to the same `film-production` task queue. Temporal will distribute workflow tasks across all available workers automatically. Third, the database tier: read-heavy endpoints (project listing, polling) can be served from a read replica. The `pgvector` IVFFlat index enables fast similarity search at scale, though for millions of vectors you would increase `lists` in the index and tune `probes`. Fourth, Kafka is already horizontally scalable — add more brokers and increase partition counts on high-traffic topics. Fifth, MinIO can be replaced with Amazon S3 in production, which handles essentially unlimited storage.

**Follow-up: What are the bottlenecks you'd expect first under load?**

The Groq API rate limits will be the first bottleneck — Groq's free tier has relatively low tokens-per-minute limits. Under load, multiple concurrent `research_topic` activities will all try to call Groq simultaneously and hit rate limit errors (HTTP 429). The mitigation is: implement a Redis-based token bucket rate limiter shared across all workers, queue overflow work to a `film.commands.research` Kafka topic with a dedicated slow-lane consumer, and eventually upgrade to a paid Groq or OpenAI tier. The second bottleneck is the `SentenceTransformer` model load time — the first activity execution loads the model from disk (several hundred MB). Under Kubernetes, a shared ReadOnlyMany volume or a model sidecar that pre-loads the model helps. Third, `pool_pre_ping=True` adds a small overhead to every connection checkout from the pool, which under high concurrency becomes measurable — in production you might disable it and instead handle `OperationalError` retries explicitly.

---

### Q: What happens if the Worker process crashes mid-workflow?

**Answer:** This is exactly the scenario Temporal is designed for, and the answer is: nothing bad happens from a data integrity perspective. Temporal maintains the complete event history of every workflow execution in its PostgreSQL database. When the Worker crashes, the currently-executing activity's heartbeat times out. The Temporal server marks that activity attempt as failed and places the activity task back on the `film-production` task queue. When the Worker restarts (or when a new Worker instance starts), it polls the queue, receives the activity task, and executes it again from the beginning. The `ResearchInput` and all necessary parameters are included in the task — the Worker has everything it needs. The retry policy (`initial_interval=5s, maximum_attempts=3`) governs how long Temporal waits before retrying. The key is that activity code must be idempotent or handle partial state. In `research_topic`, if the activity crashes after calling Groq but before writing to the database, the retry will call Groq again. This is acceptable — it wastes some tokens but produces correct results. A more robust version would write a "groq_called" flag to Redis with the result, and check it on the next attempt before calling Groq again.

**Follow-up: What if the Temporal server itself crashes?**

Temporal is designed for high availability. In production, Temporal runs as a cluster with multiple Frontend, History, Matching, and Worker service instances. The PostgreSQL backend stores all durable state. If one Temporal node crashes, others continue serving requests. The workflow history is not lost because it is persisted in PostgreSQL, not in memory. For our single-node development setup using `temporalio/auto-setup:1.24.2`, a crash would mean pending workflows are paused until Temporal restarts, at which point they resume from where they left off. No workflow state is lost because it was all written to `temporal-db`.

---

### Q: How would you handle secrets in production instead of .env files?

**Answer:** The current development setup uses a `.env` file with plaintext secrets like `GROQ_API_KEY` and `MINIO_SECRET_KEY`. This is appropriate for local development but completely inappropriate for production. The production approach has several layers. First, secrets are never committed to version control — `.env` is in `.gitignore` and `.env.example` contains only placeholder values. Second, in a Kubernetes deployment, secrets are stored in Kubernetes Secrets objects (which are base64-encoded and RBAC-controlled) and mounted as environment variables or files into pods. Third, for enterprise deployments, a dedicated secrets manager like AWS Secrets Manager, HashiCorp Vault, or GCP Secret Manager is used — these provide secret rotation, audit logging, and fine-grained access control. The application code itself doesn't need to change: `pydantic-settings` in `film/core/config.py` reads from environment variables, so whether those variables come from a `.env` file or from Kubernetes secret injection is transparent. `@lru_cache` on `get_settings()` ensures settings are loaded once at startup, not re-read on every call.

---

### Q: What monitoring would you add to this system in production?

**Answer:** Monitoring falls into four categories. First, infrastructure metrics: use Prometheus with exporters for PostgreSQL (postgres_exporter), Redis (redis_exporter), Kafka (kafka_exporter), and the Python application (prometheus_fastapi_instrumentator). Key metrics include database connection pool utilization, Redis memory usage, Kafka consumer lag per group/topic, and API request duration histograms by route and status code. Second, application-level metrics: track Groq API call latency and error rate, embedding generation time, workflow completion rate, and per-project phase durations. These would be emitted as custom Prometheus counters and histograms. Third, distributed tracing: integrate OpenTelemetry to trace a request from the API through Temporal to the activity and database. This makes it easy to identify where time is spent when a production takes unexpectedly long. Fourth, structured logging: structlog is already configured to emit JSON logs in production (`JSONRenderer` when `environment != "development"`). These JSON logs would be shipped to a log aggregation platform (Datadog, Grafana Loki, Elasticsearch) for search and alerting. Alerting would fire on: high `film.project.failed` Kafka event rate, Temporal worker heartbeat failure, database connection pool exhaustion, and Groq API error rate above 5%.

---

### Q: How would you test the Temporal activities?

**Answer:** Testing Temporal activities has three levels. Level one — unit testing — is the most important: since activities are just async functions decorated with `@activity.defn`, you can call them directly in pytest without any Temporal infrastructure. In `tests/test_projects.py`, we use `AsyncMock` for the database session and the Groq client. For example, testing `research_topic` without real Groq: mock `AsyncGroq().chat.completions.create` to return a fake response object, mock `AsyncSessionFactory()` to return a mock session, and assert that `db.add()` was called with `ResearchChunk` objects having non-empty embeddings. Level two — integration testing — uses pytest markers (`@pytest.mark.integration`) and requires the real Docker Compose stack running. The `test_project_lifecycle` test in `tests/test_projects.py` creates a project via the API, then queries it back and cancels it, verifying the full create-get-list-cancel lifecycle against real PostgreSQL. Level three — workflow testing — uses Temporal's `WorkflowEnvironment.start_local()` which runs an in-memory Temporal server for tests. You can run the full `FilmProductionWorkflow` with mocked activities in a pytest test without a real Temporal server.

**Follow-up: How are database dependencies mocked in unit tests?**

In `tests/conftest.py`, the `client` fixture creates an `AsyncClient` using `ASGITransport(app=app)` which runs the FastAPI app in-process without a real HTTP server. The lifespan is NOT triggered — the test client bypasses startup. Instead, individual dependencies are overridden via `app.dependency_overrides[get_db] = override_db`. In `test_get_project_not_found`, a `mock_session = AsyncMock()` is created, `mock_result.scalar_one_or_none.return_value = None` simulates an empty database result, and the mock session is injected via `override_db`. This means the test runs completely in-memory with no real database connection. The `autouse=True` fixture `mock_redis` in `conftest.py` automatically injects a fake Redis client for every test function in the test suite.

---

### Q: What is idempotency and how does Temporal handle it?

**Answer:** Idempotency means that performing the same operation multiple times has the same observable effect as performing it once. In distributed systems, idempotency is crucial because network failures make it impossible to know if a request was received — you might need to retry, and if the server received the first attempt, you'd execute the operation twice. Temporal provides idempotency at the workflow level via deterministic workflow IDs: `await temporal.start_workflow(..., id=f"film-{project.id}")` — if called twice with the same workflow ID, Temporal raises `WorkflowAlreadyStartedError` or returns the existing workflow handle (depending on `id_reuse_policy`). At the activity level, Temporal tracks completed activities in the event history: if an activity completes successfully, its result is replayed from history on any subsequent workflow replay — the activity function is never called again for the same workflow execution. However, if an activity is retried (because it failed), the developer must ensure idempotency: calling `research_topic` twice with the same `project_id` will create duplicate `ResearchChunk` rows. A production solution would check if chunks already exist before inserting, or use an upsert with a unique constraint on `(project_id, chunk_index)`.

**Follow-up: How would you make the research_topic activity idempotent?**

Three approaches, from simplest to most robust: First, add a unique constraint on `(project_id, chunk_index)` in the database and use PostgreSQL's `INSERT ... ON CONFLICT DO NOTHING` via SQLAlchemy's `insert(...).on_conflict_do_nothing()`. This means duplicate inserts silently succeed without error. Second, before calling Groq, query `SELECT COUNT(*) FROM research_chunks WHERE project_id = ?`. If chunks already exist and project status is `researching` with progress >= 20, the activity was already completed successfully and can return early with the stored chunk count. Third, use Temporal's activity heartbeat (`activity.heartbeat(checkpoint_data)`) to checkpoint progress within the activity, so a retry can resume from a known-good state rather than restarting from scratch. For this project, the first approach (unique constraint + on-conflict-do-nothing) would be added in Phase 2 as part of productionizing the research activity.

---

### Q: What is the pydantic-settings pattern used in this project?

**Answer:** `pydantic-settings` v2 provides a `BaseSettings` class that reads configuration from environment variables and `.env` files with full Pydantic type validation. In `film/core/config.py`, `class Settings(BaseSettings)` inherits from `BaseSettings` with `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`. The `env_file=".env"` tells pydantic-settings to look for a `.env` file in the current directory. `extra="ignore"` means environment variables that don't correspond to a Settings field are silently ignored rather than raising a validation error — important in environments like Kubernetes that inject many extra env vars. Each field has a default value, making the app runnable with a minimal configuration. The `@lru_cache` decorator on `get_settings()` means the Settings object is instantiated only once per process — subsequent calls return the cached instance. This is important for performance (you don't re-parse the `.env` file on every request) and for testability (tests can clear the cache with `get_settings.cache_clear()` to inject different values).

**Follow-up: How does structlog improve logging over Python's standard logging module?**

`structlog` adds structured, context-aware logging on top of Python's standard `logging` module. The key difference is that `structlog` encourages logging as key-value pairs rather than formatted strings. `logger.info("research_complete", chunks=len(chunks), tokens=total_tokens)` produces a log record that can be rendered as a human-readable colored string in development (`ConsoleRenderer`) or as a JSON object in production (`JSONRenderer`): `{"event": "research_complete", "chunks": 7, "tokens": 1234, "timestamp": "2025-05-18T10:00:00Z"}`. JSON-structured logs are machine-parseable by log aggregation systems — you can filter by `chunks > 5` or group by `project_id` without regex parsing. `structlog.contextvars.merge_contextvars` allows you to bind context variables (like `project_id`) to the logging context for the duration of a request, so every log line automatically includes `project_id` without explicitly passing it to every log call. In `film/activities/research.py`, `log = logger.bind(project_id=inp.project_id, topic=inp.topic)` creates a bound logger that includes these fields in all subsequent log lines within that activity execution.

---

### Q: Walk me through how you would add a new phase (e.g., scripting) to the pipeline.

**Answer:** Adding a scripting phase to the pipeline involves changes to six files. First, create `film/activities/scripting.py` with a `@activity.defn(name="write_script")` async function. This activity receives a `ScriptInput` dataclass with `project_id`, `topic`, `duration_minutes`, and `tone`. It queries `ResearchChunk` rows from the database for the given `project_id`, embeds a query string, does a pgvector cosine similarity search to find the most relevant chunks, constructs a scripting prompt, calls the Groq API, and stores the resulting script text (either in a new `Script` table or in MinIO as a `.txt` file). Second, modify `film/db/models.py` to add a `Script` ORM model if storing in the database. Third, write an Alembic migration for the new table. Fourth, modify `film/workflows/production.py` to add a `write_script` execution between `research_topic` and `mark_completed`: `script_result = await workflow.execute_activity(write_script, ScriptInput(...), start_to_close_timeout=timedelta(minutes=10), retry_policy=RETRY)`. Fifth, update `film/temporal/worker.py` to register `write_script` in the `activities=[...]` list. Sixth, update the `progress` milestones — research goes 0-20%, scripting goes 20-50%. The frontend's `PHASES` array in `types/index.ts` already defines script as `progressRange: [25, 50]` and will automatically reflect the new phase as the project status updates.

---

### Q: Explain the async context manager pattern used with the database session.

**Answer:** In `film/db/session.py`, `get_db_session` is an async generator that yields an `AsyncSession`:

```python
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        yield session
```

The `async with AsyncSessionFactory() as session:` block opens a new session at the start and ensures it is closed (and the connection returned to the pool) when the block exits — whether normally or via an exception. The `yield session` hands the session to the caller. In FastAPI, the `Depends(get_db_session)` dependency injection framework handles the entire lifecycle: the code before `yield` runs before the route handler, the session is available inside the handler, and the code after `yield` (the `async with` cleanup) runs after the route handler returns. In Temporal activities, we use `async with AsyncSessionFactory() as db:` directly (not via Depends, since Temporal activities are not FastAPI routes). This pattern ensures sessions are never leaked — even if the activity raises an exception, the `async with` block's `__aexit__` will close the session and return the connection to the pool.

---

### Q: How does the frontend handle the case where a project transitions through multiple statuses during a polling interval?

**Answer:** The frontend's polling is purely pull-based — it fetches the current server state and replaces the previous state. If a project goes from `researching` to `completed` between two poll cycles, the frontend simply sees `completed` on its next fetch and renders the completed state correctly. There is no mechanism to "replay" intermediate states — the UI never shows `researching` in that case. For a Phase 1 MVP this is acceptable, but for production you might want a WebSocket or Server-Sent Events connection that pushes state changes as they happen. An alternative approach: since we publish lifecycle events to Kafka (`film.research.completed`, `film.project.completed`), a future WebSocket service can consume these events and push them to connected clients in real time, eliminating polling entirely. The `refetchInterval: 3_000` and `4_000` values in `ProjectDetail.tsx` and `Dashboard.tsx` are a reasonable trade-off between responsiveness (user sees updates within 4 seconds) and server load (each polling client generates ~15 requests/minute).

---

### Q: What does the fetch wrapper in api/client.ts handle?

**Answer:** The `request<T>()` function in `frontend/src/api/client.ts` is a thin typed wrapper around the browser's native `fetch` API. It adds two headers to every request: `Content-Type: application/json` (required for POST requests with a JSON body) and `X-User-ID: 550e8400-e29b-41d4-a716-446655440000` (the hardcoded test user ID for Phase 1). It checks `res.ok` (true for 200-299 status codes) and if false, attempts to parse the error body as JSON to extract the `detail` field (which is the FastAPI/Pydantic error format), falling back to the HTTP status text. The function is generic (`<T>`) and calls `res.json()` with the return type annotation, giving TypeScript callers full type inference without explicit casting. The `api` export object organizes calls by resource — `api.projects.list()`, `api.projects.get(id)`, `api.projects.create(payload)`, `api.projects.cancel(id)` — mirroring the backend REST resource hierarchy and making call sites easy to read.

---

### Q: What would you change about this architecture if you were starting over?

**Answer:** Several things would change. First, I would add proper JWT-based authentication from day one rather than the `X-User-ID` header shortcut. Even if the UI doesn't have login screens in Phase 1, having a real auth layer means you don't have to do a breaking API change later when auth is needed. Second, I would implement the Kafka Dead Letter Queue (the `DLQ = "film.dlq.failed_events"` topic is already defined but the DLQ routing in `FilmConsumer._process()` is marked as a TODO). In production, messages that fail processing should go to the DLQ with full context so they can be inspected and replayed. Third, I would add OpenTelemetry distributed tracing from the start — adding it later requires touching every module. Fourth, I would make the `SentenceTransformer` model loading happen at Worker startup (in `run_worker()`) rather than lazily on first activity call, so the cold-start latency is paid once, not on a user-facing workflow. Fifth, the activity idempotency gap — duplicate `ResearchChunk` inserts on retry — should be addressed with a unique constraint and upsert before going to production.

---

## 13. Script Generation Activity

### Q: Walk me through how the `generate_script` activity works end to end.

**Answer:** The activity lives in `film/activities/script.py` and is decorated with `@activity.defn`. It receives a `ProjectContext` object containing the project ID, title, logline, and target duration in minutes. The flow has five steps. Step one: fetch all `ResearchChunk` rows for the project from PostgreSQL using a plain SQLAlchemy `select(ResearchChunk).where(ResearchChunk.project_id == ctx.project_id)` query — no vector similarity search yet, just a bulk fetch. Step two: concatenate the `text` fields from all chunks and trim the combined string to 6000 characters to stay within Groq's context window. Step three: call `_estimate_scenes(ctx.duration_minutes)` to decide how many scenes to request, then build a structured prompt that includes the TITLE, LOGLINE, ACT structure, and a per-scene format specifying SCENE N, LOCATION, DURATION, NARRATION, VISUALS, and TRANSITION. This prompt is sent to Groq using the `llama-3.3-70b-versatile` model with `temperature=0.8` and `max_tokens=4096`. Step four: the raw script text returned by Groq is stored in a new `Asset` row with `type="script"` and `meta={"content": script_text, "scenes": scenes_written}`. An `AIUsage` row is also logged with `provider="groq"` and `operation="script_generation"`. Step five: the project's status is updated to `scripting` at the start (progress 25%) and the progress is bumped to 40% on completion. The activity returns a `ScriptOutput` dataclass with `scenes`, `total_tokens`, and `asset_id`.

**Follow-up: Why trim the research text to 6000 characters?**

Groq's `llama-3.3-70b-versatile` model has a context window limit, and the script generation prompt itself already consumes a substantial portion of that window — the ACT structure, per-scene format instructions, TITLE, and LOGLINE are all included before we even append the research. Trimming the research to 6000 characters leaves room for the prompt overhead and the model's 4096-token output without hitting a context-length error. A more sophisticated approach — which Phase 4 introduces — is to use RAG to select only the most relevant research chunks rather than blindly truncating. But for Phase 3, the trim is a pragmatic guard against failures.

**Follow-up: Why store the script inside `Asset.meta["content"]` instead of a dedicated Script table?**

The `Asset` table is designed as a general-purpose content store — it already has a `type` discriminator field and a `meta` JSONB column, so storing the script there required zero schema changes and no new Alembic migration. A dedicated `Script` table would give you better queryability (indexed columns for scene count, word count, etc.) and cleaner foreign key relationships, but in Phase 3 the only operation on the script is "store it, then retrieve it whole." The JSONB meta column handles that perfectly. When the system matures and needs to query across script metadata — filtering by scene count, joining to storyboard frames — migrating to a dedicated table is straightforward because the `Asset` row with `type="script"` already acts as the foreign key anchor.

**Follow-up: What does `temperature=0.8` mean and why is it higher than the research activity call?**

Temperature controls the randomness of the model's token sampling. At `temperature=0.0` the model always picks the highest-probability next token — fully deterministic, factually conservative. At `temperature=1.0` sampling is maximally random. The research activity uses a lower temperature because it's summarizing factual material and accuracy matters more than creativity. The script generation activity uses `temperature=0.8` because documentary scriptwriting benefits from creative variation — a slightly warmer temperature produces more varied sentence structures, more evocative narration, and scene descriptions that don't sound formulaic. If you ran script generation at `temperature=0.0`, every documentary on the same topic would read identically, which is undesirable.

---

### Q: How did you structure the script generation prompt and why?

**Answer:** The prompt is a structured natural-language specification that gives the model enough constraints to produce parseable output without needing a formal schema. The outer frame sets the role: "You are a documentary scriptwriter." Then it injects the project metadata — TITLE and LOGLINE — so the model understands the creative brief. The ACT structure section tells the model to write a three-act documentary (setup, development, resolution), then specifies the exact number of scenes to produce based on `_estimate_scenes()`. For each scene the prompt requires six labelled fields: `SCENE N` (integer), `LOCATION` (setting description), `DURATION` (seconds), `NARRATION` (voiceover text), `VISUALS` (shot descriptions), and `TRANSITION` (cut/dissolve/fade). The research text is appended at the end under a `RESEARCH CONTEXT:` header. This format mirrors how professional documentary scripts are laid out, which leverages the model's pre-training on real scripts.

**Follow-up: What happens if Groq doesn't follow the format exactly?**

In Phase 3, the script text is stored verbatim — there is no strict parser that enforces the six-field schema. The `scenes_written` count in `Asset.meta` is derived by counting occurrences of the `SCENE` label in the output text (e.g., `output.count("SCENE ")`). If Groq deviates — skipping a VISUALS block, merging two scenes, or adding extra prose — the text is still stored as-is and the scene count may be slightly off. The frontend displays the script as a raw pre-formatted block, so the user sees whatever Groq produced. For Phase 4, when the storyboard activity needs to extract individual scenes to generate images, a more robust parser (regex or a second LLM call for structured extraction) will be necessary. This is a known limitation called out in the codebase's TODO comments.

**Follow-up: How do you count scenes in the output?**

The `scenes_written` field stored in `Asset.meta` is computed by counting the number of `"SCENE "` prefix occurrences in the returned script string. This is intentionally simple — a regex like `len(re.findall(r"^SCENE \d+", text, re.MULTILINE))` would be more precise, but a plain string count works reliably enough given that "SCENE " as a standalone label is unlikely to appear in narration or visuals text. The count is informational at this stage — it drives the scene count badge displayed in the frontend's script panel.

---

### Q: How does `_estimate_scenes` work and why?

**Answer:** `_estimate_scenes(duration_minutes: int) -> int` is a one-liner helper: `return max(4, duration_minutes // 2)`. Integer floor division by 2 maps the documentary duration directly to a scene count — a 10-minute documentary gets 5 scenes, a 20-minute documentary gets 10, a 30-minute documentary gets 15. The `max(4, ...)` guard ensures that even a very short documentary (under 8 minutes) always has at least 4 scenes, since a three-act documentary with fewer than 4 scenes would feel structurally inadequate (you can't have a meaningful setup, two development beats, and a resolution in 3 scenes or fewer).

**Follow-up: What's the trade-off of more versus fewer scenes?**

More scenes gives the model more structure to work with: each scene is shorter in word count, which makes the NARRATION and VISUALS blocks more focused and easier to translate into storyboard images in Phase 4. However, more scenes means more Groq API output tokens, which increases cost and latency. It also means more rows to store in the storyboard and more image generation calls. Fewer scenes produces longer, more free-form narration blocks that are richer in prose but harder to map to discrete visual shots. The `duration // 2` heuristic approximates a 2-minutes-per-scene rhythm, which aligns with documentary pacing conventions where a scene typically lasts 1.5–3 minutes.

---

### Q: What is `ScriptOutput` and why use a dataclass?

**Answer:** `ScriptOutput` is a Python `@dataclass` defined in `film/activities/script.py` (or a shared models file) with three fields: `scenes: int`, `total_tokens: int`, and `asset_id: str`. Temporal activities must return values that are serializable to JSON so Temporal can persist them in its event history — if the Worker crashes mid-workflow, Temporal replays the workflow from its history and injects the previously-returned value rather than re-running the completed activity. Python dataclasses serialize cleanly to JSON via Temporal's built-in `dataclasses.asdict()` serialization path. They also provide type-safe attribute access in the workflow code that receives the return value: `result.scenes`, `result.asset_id` — no dict key typos at runtime.

**Follow-up: What would happen if you returned a SQLAlchemy model object instead?**

SQLAlchemy ORM objects are not JSON-serializable by default. A `ScriptOutput` returned as an `Asset` ORM instance would cause Temporal's serializer to raise an exception when it tried to persist the activity result to its event history. Additionally, ORM objects hold a reference to the database session they were loaded from — after the session is closed (which happens at the end of the `async with AsyncSessionFactory()` block), accessing lazy-loaded relationships on the ORM object would raise a `DetachedInstanceError`. Returning a plain dataclass avoids both problems: it's a pure data structure with no session attachment and trivially serializable.

---

## 14. RAG — What We Built vs What We Used

### Q: You mention RAG — what exactly did you implement and what's still pending?

**Answer:** RAG has two distinct phases: indexing and retrieval. As of Phase 3, we have fully implemented the indexing phase but have not yet used retrieval. In Phase 2, the `research_topic` activity chunked the Groq research output into segments, ran each through `SentenceTransformer("all-MiniLM-L6-v2")` to produce a 384-dimensional embedding vector, and stored each chunk as a `ResearchChunk` row in PostgreSQL with its `embedding vector(384)` column populated. The IVFFlat index on that column is in place. In Phase 3, the `generate_script` activity fetches research with a plain SQL `SELECT` — it retrieves all chunks for the project indiscriminately, concatenates their text, and trims to 6000 characters. No vector similarity query is performed. Phase 4 (storyboarding) will be the first place actual RAG retrieval is used: for each scene, the storyboard activity will embed the scene's narration text and query `ORDER BY embedding <=> query_vector LIMIT K` to find the top-K most semantically relevant research chunks, which will then be passed as focused context to the image prompt generator.

**Follow-up: Why didn't you use vector search in Phase 3?**

Script generation benefits from broad context — you want the LLM to have a holistic view of all the research when writing the narrative arc across all scenes. Retrieving only the top-K similar chunks for a single query vector would lose chunks that are relevant to the second or third act but not the most similar to any single query. Since the total research for a typical project fits within 6000 characters after trimming, there was no practical need for selective retrieval. Phase 4 operates at the scene level — each scene has a specific narrative focus — which is exactly when selective retrieval pays off.

**Follow-up: What's the difference between "storing embeddings" and "using RAG"?**

Storing embeddings is the offline indexing step: you take your source documents, convert them to vector representations, and persist those vectors alongside the source text. This makes future retrieval possible but doesn't constitute RAG by itself. Using RAG means that at query time — when you're about to call an LLM — you first embed your query, perform a vector similarity search against the stored embeddings to find the most semantically relevant documents, and then inject those retrieved documents as context into the LLM prompt. The LLM's answer is thus "grounded" in the retrieved content rather than generated purely from its parametric memory. We have the index. The retrieval-augmented generation step comes in Phase 4.

---

### Q: Explain the full RAG flow you're building toward.

**Answer:** The target RAG flow in Phase 4 works as follows. During indexing (already done in Phase 2): the research text is split into overlapping chunks of roughly 500 characters, each chunk is passed through `SentenceTransformer("all-MiniLM-L6-v2")` to produce a 384-dim float vector, and the vector is stored in the `research_chunks.embedding` column in PostgreSQL with the pgvector extension. An IVFFlat index with `lists=100` is built on that column. During retrieval (Phase 4): when the storyboard activity processes Scene N, it takes the scene's `NARRATION` text, embeds it with the same `SentenceTransformer` model to get a query vector, then issues a PostgreSQL query: `SELECT text FROM research_chunks WHERE project_id = :pid ORDER BY embedding <=> :qvec LIMIT 5`. The `<=>` operator is pgvector's cosine distance operator. The top-5 returned chunks are concatenated and injected into the image prompt as a `CONTEXT:` block. The LLM generating the visual description is therefore grounded in the specific research passages most relevant to that scene's narration.

**Follow-up: Why is RAG better than just passing all research to the LLM?**

Two reasons: context window limits and signal-to-noise ratio. LLMs have finite context windows — the full research corpus for a long documentary could easily exceed 50,000 tokens, which is impractical to include in every prompt. RAG lets you include only the 5–10 most relevant chunks, staying well within limits. Even within the context window, irrelevant text degrades output quality: studies show that LLMs have difficulty "finding the needle" when the relevant passage is buried in a long context. Retrieving only the semantically closest chunks means the model's attention is focused on what matters for the current generation task.

**Follow-up: What is the IVFFlat index and why does it matter at scale?**

IVFFlat stands for Inverted File Flat. It partitions the vector space into `lists` clusters (configured as 100 in our migration) using k-means during index build time. At query time, instead of comparing the query vector against every row in the table (exact nearest neighbor search, O(n)), the index identifies the closest cluster centroids first and only searches within those clusters. This reduces the search space dramatically — with `lists=100` and default `probes=10`, pgvector searches roughly 10% of the data. The trade-off is that it's approximate: a result in a neighboring cluster might be missed. For a production system with millions of chunks this speed improvement is essential. For our current scale (hundreds of chunks per project) it makes no measurable difference, but the index is cheap to maintain and the habit of indexing correctly from the start avoids a painful backfill migration later.

---

### Q: What embedding model are you using and why?

**Answer:** We use `sentence-transformers/all-MiniLM-L6-v2`, which produces 384-dimensional embeddings. It was chosen for three reasons. First, it runs entirely on CPU — there's no GPU requirement, which keeps the Docker Compose stack runnable on a standard development laptop without a CUDA-enabled GPU. Second, it's fast: embedding a 500-character chunk takes under 10 milliseconds on CPU. Third, it achieves strong results on semantic similarity benchmarks despite its small size — it was specifically trained on a large collection of sentence pairs for semantic textual similarity tasks, which is exactly what we need for finding research chunks relevant to a given narration sentence. The model is downloaded once via the `sentence-transformers` library and cached locally; there are no API calls, no per-token costs, and no network latency on subsequent uses.

**Follow-up: Why not use OpenAI's embedding API instead?**

Three reasons: cost, latency, and availability. OpenAI's `text-embedding-3-small` model costs money per token and requires an API key with billing enabled. For a Phase 1 pipeline that might embed thousands of chunks during development and testing, those costs add up without delivering value over a local model. OpenAI embeddings also add network latency on every embed call — embedding a batch of 20 chunks requires a round-trip to OpenAI's servers. Most importantly, using a third-party embedding API introduces an external dependency that can be rate-limited, throttled, or unavailable, causing activity failures. Running `all-MiniLM-L6-v2` locally eliminates all three concerns.

**Follow-up: What's the trade-off between 384 dimensions versus 1536 dimensions?**

Higher-dimensional embeddings can capture more nuanced semantic distinctions — `text-embedding-3-large` uses 3072 dimensions and `text-embedding-ada-002` uses 1536. More dimensions generally means better retrieval precision, particularly for subtle topic distinctions. However, higher dimensions increase storage (1536 floats × 4 bytes = 6144 bytes per chunk vs. 384 × 4 = 1536 bytes), slow down cosine similarity computation, and make the IVFFlat index larger and slower to build. For documentary research chunks — which tend to be topically coherent and semantically distinct — 384 dimensions provides sufficient resolution to separate "Battle of Thermopylae tactics" from "Persian Empire trade routes." If retrieval precision became a bottleneck in production, upgrading to a higher-dimensional model would be a targeted optimization rather than an upfront requirement.

**Follow-up: What does `normalize_embeddings=True` do?**

When `normalize_embeddings=True` is passed to `model.encode()`, each returned vector is divided by its L2 norm, making it a unit vector with magnitude 1. This is important for cosine similarity: cosine similarity between two vectors is defined as their dot product divided by the product of their magnitudes. When both vectors are unit vectors, the dot product equals the cosine similarity directly. pgvector's `<=>` cosine distance operator (`1 - cosine_similarity`) produces correct results regardless of normalization, but normalizing at encode time means you could also use the inner product operator `<#>` (negative inner product) for retrieval, which is computationally cheaper. Normalized embeddings also ensure that the magnitude of the text (longer texts with more repeated terms would otherwise produce larger vectors) does not artificially inflate similarity scores.

---

## 15. API Design — Script Endpoint

### Q: Why return the script content inside the API response instead of a separate file or URL?

**Answer:** The script is plain UTF-8 text — typically 2,000–8,000 characters for a 10–30 minute documentary. Returning it inline in the JSON response is the simplest design that works: no pre-signed URL generation, no MinIO round-trip, no separate download step in the frontend. The `GET /api/v1/projects/{project_id}/script` endpoint in `film/api/v1/projects.py` fetches the `Asset` row with `type="script"`, reads `asset.meta["content"]`, and returns a JSON object with `project_id`, `asset_id`, `scenes`, `content`, and `created_at`. The frontend receives the full script in a single fetch and renders it in a scrollable `<pre>` block. This is appropriate for text payloads under ~100KB — which all realistic documentary scripts are.

**Follow-up: At what point would you switch to returning a MinIO URL instead?**

Once the generated assets become large binaries — storyboard images, audio narration files, video segments — returning them inline becomes impractical. The threshold is roughly when the payload exceeds what you'd comfortably embed in JSON (conventionally ~1MB). For those cases, the `Asset` table has a `storage_path` column designed to hold a MinIO object path. The API would instead return a pre-signed URL generated by the MinIO client: `minio_client.presigned_get_object("film-assets", asset.storage_path, expires=timedelta(hours=1))`. The frontend would then open that URL directly in a `<video>` or `<img>` tag, bypassing the API server entirely for the large payload transfer.

**Follow-up: Why does the endpoint return 404 instead of 202 when the script isn't ready yet?**

A 202 Accepted would be semantically correct if the resource is being generated and the client should retry. However, returning 202 requires the client to distinguish between "accepted, keep polling" and "not found, stop trying." In this design, the frontend already has that context from the project's `status` field — the script query is only enabled when `project.status === 'completed'`. If the project is completed but the `Asset` row with `type="script"` is missing, that is a genuine data integrity problem (the workflow failed to store the asset), not a transient "still generating" state. Returning 404 in that case clearly signals "this resource does not exist" so the developer can investigate rather than the client silently retrying indefinitely. Using the project status as the gate prevents the 404 from being a normal condition during happy-path operation.

---

### Q: How does the frontend know when to fetch the script?

**Answer:** In `ProjectDetail.tsx`, the TanStack Query hook for the script is configured with `enabled: !!id && project?.status === 'completed'`. The `!!id` guard prevents firing before the project ID is known from the URL params. The `project?.status === 'completed'` guard means the script query is entirely suppressed — not just failing silently — while the project is in `pending`, `researching`, or `scripting` states. TanStack Query respects `enabled: false` by not scheduling the fetch at all, producing no network requests and no loading spinner for the script panel until the condition is met. Once the project transitions to `completed` (detected on the next 3-second polling tick of the project query), `enabled` becomes `true` and TanStack Query immediately fires the script fetch.

**Follow-up: What's the risk of polling for the script before the project is completed?**

If the script query were enabled during `scripting` status, it would repeatedly hit `GET /api/v1/projects/{id}/script` and receive 404 responses every 3 seconds. TanStack Query's default retry behavior would treat 404 as a retryable error and back off, but the net effect is unnecessary load on the database (each 404 requires a DB query to confirm the Asset row doesn't exist) and confusing error state in the UI. More subtly, if a flaky network caused the 404 to be returned after the script was actually stored, the query might cache the 404 and not refetch — leading to a "script ready on server, 404 cached on client" bug. Gating on `status === 'completed'` avoids all of this.

**Follow-up: Why `retry: false` on the script query?**

The script query uses `retry: false` because the only expected non-200 response is 404 (script not yet generated or genuinely missing), and retrying a 404 is pointless — the server state hasn't changed between retries. TanStack Query's default retry logic (3 retries with exponential backoff) is designed for transient network errors, not semantic "not found" responses. If the script genuinely doesn't exist because the workflow failed, retrying will just produce the same 404 three times and delay showing the error state to the user by several seconds. With `retry: false`, the first 404 immediately sets the query to error state, which the frontend can surface as a "script unavailable" message rather than a loading spinner that eventually times out.

---

*End of Phase 3 interview preparation. This document now covers Phases 1–3 of the AI Film Production Pipeline including system design, all backend services, the React frontend, and the script generation pipeline with RAG context.*
