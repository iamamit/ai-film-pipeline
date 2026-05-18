# ── Lifecycle events (published by workers after each phase) ─────────────────
PROJECT_CREATED = "film.project.created"
PROJECT_STARTED = "film.project.started"
RESEARCH_COMPLETED = "film.research.completed"
SCRIPT_COMPLETED = "film.script.completed"
STORYBOARD_COMPLETED = "film.storyboard.completed"
ASSETS_COMPLETED = "film.assets.completed"
ASSEMBLY_COMPLETED = "film.assembly.completed"
PROJECT_COMPLETED = "film.project.completed"
PROJECT_FAILED = "film.project.failed"

# ── Worker commands (consumed by specialized workers) ────────────────────────
CMD_RESEARCH = "film.commands.research"
CMD_SCRIPT = "film.commands.script"
CMD_STORYBOARD = "film.commands.storyboard"
CMD_VOICE = "film.commands.generate_voice"
CMD_IMAGES = "film.commands.generate_images"
CMD_ASSEMBLE = "film.commands.assemble"

# ── Dead letter queue ────────────────────────────────────────────────────────
DLQ = "film.dlq.failed_events"

ALL_TOPICS: list[str] = [
    PROJECT_CREATED, PROJECT_STARTED, RESEARCH_COMPLETED, SCRIPT_COMPLETED,
    STORYBOARD_COMPLETED, ASSETS_COMPLETED, ASSEMBLY_COMPLETED,
    PROJECT_COMPLETED, PROJECT_FAILED,
    CMD_RESEARCH, CMD_SCRIPT, CMD_STORYBOARD, CMD_VOICE, CMD_IMAGES, CMD_ASSEMBLE,
    DLQ,
]
