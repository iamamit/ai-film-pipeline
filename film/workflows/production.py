"""FilmProductionWorkflow — orchestrates the full documentary pipeline."""
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from film.activities.research import ResearchInput, ResearchOutput, research_topic
    from film.activities.script import ScriptInput, ScriptOutput, generate_script
    from film.activities.storyboard import StoryboardInput, StoryboardOutput, generate_storyboard
    from film.activities.assets import AssetsInput, AssetsOutput, generate_assets
    from film.activities.finalize import mark_completed


@dataclass
class ProductionInput:
    project_id: str
    topic: str
    duration_minutes: int
    tone: str


RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)


@workflow.defn(name="FilmProductionWorkflow")
class FilmProductionWorkflow:
    @workflow.run
    async def run(self, inp: ProductionInput) -> str:
        workflow.logger.info(f"workflow_started project_id={inp.project_id} topic={inp.topic}")

        # Phase 1: Research (0% → 20%)
        research_result: ResearchOutput = await workflow.execute_activity(
            research_topic,
            ResearchInput(
                project_id=inp.project_id,
                topic=inp.topic,
                duration_minutes=inp.duration_minutes,
                tone=inp.tone,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RETRY,
        )
        workflow.logger.info(
            f"research_done chunks={research_result.chunks_stored} tokens={research_result.total_tokens}"
        )

        # Phase 2: Script Generation (20% → 40%)
        script_result: ScriptOutput = await workflow.execute_activity(
            generate_script,
            ScriptInput(
                project_id=inp.project_id,
                topic=inp.topic,
                duration_minutes=inp.duration_minutes,
                tone=inp.tone,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RETRY,
        )
        workflow.logger.info(
            f"script_done scenes={script_result.scenes} tokens={script_result.total_tokens}"
        )

        # Phase 3: Storyboarding (40% → 60%) — first use of RAG
        storyboard_result: StoryboardOutput = await workflow.execute_activity(
            generate_storyboard,
            StoryboardInput(
                project_id=inp.project_id,
                topic=inp.topic,
                tone=inp.tone,
            ),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RETRY,
        )
        workflow.logger.info(
            f"storyboard_done scenes={storyboard_result.scenes_processed} tokens={storyboard_result.total_tokens}"
        )

        # Phase 4: Asset Generation (60% → 80%)
        assets_result: AssetsOutput = await workflow.execute_activity(
            generate_assets,
            AssetsInput(
                project_id=inp.project_id,
                topic=inp.topic,
                tone=inp.tone,
            ),
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RETRY,
        )
        workflow.logger.info(
            f"assets_done voiceovers={assets_result.voiceovers_generated} images={assets_result.images_generated}"
        )

        # Phase 5+ (Assembly) — added in next phase
        await workflow.execute_activity(
            mark_completed,
            inp.project_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY,
        )

        return inp.project_id
