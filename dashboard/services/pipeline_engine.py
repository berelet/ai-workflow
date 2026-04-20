"""Backend pipeline orchestration engine.

Manages the state machine for pipeline execution:
  PipelineRun:  PENDING → RUNNING → COMPLETED | FAILED | CANCELLED
  StageLog:     PENDING → RUNNING → COMPLETED | FAILED | RETURNED
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.db.models.pipeline import PipelineDefinition, PipelineRun, PipelineStageLog
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.project import Project
from dashboard.services.prompt_builder import prompt_builder, AGENT_DIRS
from dashboard.services.git_manager import git_manager, GitError
from dashboard.services.artifact_manager import artifact_manager
from dashboard.services.terminal_manager import terminal_manager

MAX_AUTO_ADVANCE_DEPTH = 20  # prevent infinite loops on cyclic graphs

logger = logging.getLogger("services.pipeline_engine")


class PipelineError(Exception):
    pass


# --- Graph traversal helpers ---

def _extract_graph_data(graph_json: dict) -> dict:
    """Extract node data dict from Drawflow graph JSON."""
    return graph_json.get("drawflow", {}).get("Home", {}).get("data", {})


def _find_start_node(nodes: dict) -> Optional[str]:
    """Find the node with no incoming connections (entry point)."""
    for node_id, node in nodes.items():
        inputs = node.get("inputs", {})
        if not inputs or all(not inp.get("connections") for inp in inputs.values()):
            return str(node_id)
    return str(list(nodes.keys())[0]) if nodes else None


def _get_next_node(nodes: dict, current_id: str) -> Optional[str]:
    """Follow output connections to the next node."""
    node = nodes.get(str(current_id))
    if not node:
        return None
    for output in node.get("outputs", {}).values():
        connections = output.get("connections", [])
        if connections:
            return str(connections[0].get("node"))
    return None


def _find_node_by_agent(nodes: dict, agent: str) -> Optional[str]:
    """Find node_id by agent name (e.g., 'DEV')."""
    for node_id, node in nodes.items():
        if node.get("data", {}).get("agent") == agent:
            return str(node_id)
    return None


class PipelineEngine:

    async def start_pipeline(
        self,
        db: AsyncSession,
        project: Project,
        backlog_item: BacklogItem,
        pipeline_def: PipelineDefinition,
        user_id: uuid.UUID,
        auto_advance: bool = False,
        branch_strategy: str | None = None,
        branch_name: str | None = None,
    ) -> PipelineRun:
        """Start a new pipeline run for a task.

        Creates the run, all stage log entries, optionally creates git branch,
        and executes the first stage.
        """
        nodes = _extract_graph_data(pipeline_def.graph_json)
        if not nodes:
            raise PipelineError("Pipeline graph is empty")

        start_node_id = _find_start_node(nodes)
        if not start_node_id:
            raise PipelineError("Cannot find start node in pipeline graph")

        # Resolve repo path for THIS dashboard instance
        from dashboard.services.instance_paths import resolve_local_path
        repo_path = await resolve_local_path(db, project)

        # Create git branch based on strategy
        git_branch = None
        if repo_path:
            try:
                if branch_strategy == "new" and branch_name:
                    # User chose to create a new branch with custom name
                    git_branch = await git_manager.create_named_branch(
                        repo_path=repo_path,
                        branch_name=branch_name,
                    )
                elif branch_strategy == "current":
                    # User chose current branch
                    git_branch = await git_manager.get_current_branch(repo_path)
                else:
                    # Legacy behavior: auto-create task branch
                    git_branch = await git_manager.create_task_branch(
                        repo_path=repo_path,
                        prefix=project.prefix,
                        task_id=backlog_item.sequence_number,
                        task_title=backlog_item.title,
                        base_branch=project.base_branch or "main",
                    )
            except GitError as e:
                if branch_strategy == "new":
                    raise PipelineError(str(e))
                logger.warning("Git branch creation failed: %s", e)

        # Create pipeline run
        run = PipelineRun(
            project_id=project.id,
            pipeline_def_id=pipeline_def.id,
            backlog_item_id=backlog_item.id,
            status="running",
            current_node_id=start_node_id,
            current_stage=nodes[start_node_id].get("data", {}).get("agent", ""),
            auto_advance=auto_advance,
            git_branch=git_branch,
            started_by=user_id,
        )
        db.add(run)
        await db.flush()  # Assign run.id (UUID generated by Python default, flushed to DB)

        # Create stage log entries for all nodes
        for node_id, node in nodes.items():
            node_data = node.get("data", {})
            stage_log = PipelineStageLog(
                run_id=run.id,
                node_id=str(node_id),
                stage=node_data.get("agent", f"node_{node_id}"),
                node_type=node_data.get("type", "agent"),
                status="pending",
                agent=node_data.get("agent", ""),
            )
            db.add(stage_log)

        # Update backlog item status
        backlog_item.status = "in-progress"

        await db.commit()
        await db.refresh(run)

        logger.info(
            "Pipeline started: run=%s project=%s task=%s branch=%s",
            run.id, project.slug, backlog_item.task_id_display, git_branch,
        )

        # Execute the first stage
        await self.execute_stage(db, run, start_node_id, user_id)

        return run

    async def execute_stage(
        self,
        db: AsyncSession,
        run: PipelineRun,
        node_id: str,
        user_id: uuid.UUID,
    ) -> PipelineStageLog:
        """Execute a specific stage by spawning a terminal session.

        Builds the prompt, ensures git branch, spawns CLI process.
        """
        project = await db.get(Project, run.project_id)
        backlog_item = await db.get(BacklogItem, run.backlog_item_id)
        pipeline_def = await db.get(PipelineDefinition, run.pipeline_def_id)

        nodes = _extract_graph_data(pipeline_def.graph_json)
        node = nodes.get(str(node_id))
        if not node:
            raise PipelineError(f"Node {node_id} not found in graph")

        node_data = node.get("data", {})
        stage = node_data.get("agent", "")
        stage_upper = stage.upper()

        # Get stage log
        result = await db.execute(
            select(PipelineStageLog).where(
                PipelineStageLog.run_id == run.id,
                PipelineStageLog.node_id == str(node_id),
            )
        )
        stage_log = result.scalar_one_or_none()
        if not stage_log:
            raise PipelineError(f"Stage log not found for node {node_id}")

        # Resolve repo path for THIS dashboard instance
        from dashboard.services.instance_paths import resolve_local_path
        repo_path = await resolve_local_path(db, project)

        # Ensure git branch
        if run.git_branch and repo_path:
            try:
                await git_manager.ensure_branch(repo_path, run.git_branch)
            except GitError as e:
                stage_log.status = "failed"
                stage_log.error_message = f"Git error: {e}"
                await db.commit()
                raise PipelineError(f"Git branch error: {e}")

        # Load agent instructions (from DB or filesystem)
        from dashboard.db.models.agent_config import AgentConfig
        agent_dir_name = AGENT_DIRS.get(stage_upper, stage.lower())
        result = await db.execute(
            select(AgentConfig).where(
                AgentConfig.project_id == project.id,
                AgentConfig.agent_name == agent_dir_name,
            )
        )
        project_config = result.scalar_one_or_none()
        if not project_config:
            result = await db.execute(
                select(AgentConfig).where(
                    AgentConfig.project_id == None,
                    AgentConfig.agent_name == agent_dir_name,
                )
            )
            project_config = result.scalar_one_or_none()

        agent_instructions = prompt_builder.load_agent_instructions(
            stage=stage_upper,
            project_dir=repo_path,
            db_instructions=project_config.instructions_md if project_config else None,
        )

        # Load skills for review stages
        skills = prompt_builder.load_skills(stage=stage_upper)

        # Get input artifacts from previous stages
        input_artifacts = await artifact_manager.get_input_for_stage(db, run.id, stage_upper)

        # Load git rules for COMMIT stage
        git_rules = ""
        if stage_upper == "COMMIT" and repo_path:
            from dashboard.services.prompt_builder import _load_file
            for rules_path in [
                Path(repo_path) / "aiworkflow" / "git-rules.md",
                Path(repo_path) / ".ai-workflow" / "git-rules.md",
            ]:
                git_rules = _load_file(rules_path)
                if git_rules:
                    break

        # Callback URL from env or default
        server_port = os.environ.get("DASHBOARD_PORT", "9000")
        callback_url = f"http://localhost:{server_port}/api/pipeline/complete"

        # Build prompt
        prompt = prompt_builder.build_stage_prompt(
            stage=stage_upper,
            task_title=backlog_item.title,
            task_description=backlog_item.description or "",
            task_id_display=backlog_item.task_id_display,
            project_name=project.name,
            project_description=project.description or "",
            agent_instructions=agent_instructions,
            skills=skills,
            previous_artifacts=input_artifacts,
            git_branch=run.git_branch or "",
            git_rules=git_rules,
            custom_node_prompt=node_data.get("prompt", ""),
            pipeline_run_id=str(run.id),
            node_id=str(node_id),
            callback_url=callback_url,
        )

        # Determine CWD
        cwd = repo_path or "/tmp"

        # Spawn terminal session
        model = os.environ.get("DEFAULT_MODEL", "claude-opus-4-6")
        provider = os.environ.get("DEFAULT_CLI", "claude")

        session = await terminal_manager.spawn_session(
            user_id=user_id,
            project_id=project.id,
            prompt=prompt,
            cwd=cwd,
            provider=provider,
            model=model,
            claude_session_id=run.claude_session_id,
        )

        # Update stage log
        stage_log.status = "running"
        stage_log.started_at = datetime.now(timezone.utc)
        stage_log.terminal_session_id = session.session_id

        # Update run
        run.current_node_id = str(node_id)
        run.current_stage = stage

        await db.commit()

        logger.info(
            "Stage executing: run=%s node=%s stage=%s session=%s",
            run.id, node_id, stage, session.session_id,
        )
        return stage_log

    async def complete_stage(
        self,
        db: AsyncSession,
        pipeline_run_id: uuid.UUID,
        node_id: str,
        status: str,
        reported_artifacts: list[dict],
        message: str = "",
        return_to: str | None = None,
    ) -> dict:
        """Handle stage completion callback from an agent.

        Called via POST /api/pipeline/complete.
        """
        run = await db.get(PipelineRun, pipeline_run_id)
        if not run:
            raise PipelineError(f"Pipeline run {pipeline_run_id} not found")
        if run.status != "running":
            raise PipelineError(f"Pipeline run is {run.status}, not running")

        project = await db.get(Project, run.project_id)
        backlog_item = await db.get(BacklogItem, run.backlog_item_id)
        pipeline_def = await db.get(PipelineDefinition, run.pipeline_def_id)

        # Get stage log
        result = await db.execute(
            select(PipelineStageLog).where(
                PipelineStageLog.run_id == run.id,
                PipelineStageLog.node_id == str(node_id),
            )
        )
        stage_log = result.scalar_one_or_none()
        if not stage_log:
            raise PipelineError(f"Stage log for node {node_id} not found")
        if stage_log.status != "running":
            raise PipelineError(f"Stage {node_id} is {stage_log.status}, not running")

        # Resolve repo path for THIS dashboard instance
        from dashboard.services.instance_paths import resolve_local_path
        repo_path = await resolve_local_path(db, project)

        # Collect artifacts
        if reported_artifacts:
            await artifact_manager.collect_artifacts(
                db=db,
                project_id=project.id,
                project_visibility=project.visibility,
                project_prefix=project.prefix,
                project_dir=repo_path,
                backlog_item_id=backlog_item.id,
                task_id_display=backlog_item.task_id_display,
                stage=stage_log.stage,
                reported_artifacts=reported_artifacts,
            )

        # Update stage log
        stage_log.completed_at = datetime.now(timezone.utc)
        stage_log.output_summary = message[:500] if message else None

        nodes = _extract_graph_data(pipeline_def.graph_json)
        response = {
            "pipeline_run_id": str(run.id),
            "current_node_id": node_id,
            "pipeline_status": "running",
        }

        if status == "returned":
            # Send work back (e.g., QA FAIL → DEV)
            stage_log.status = "returned"
            stage_log.return_reason = message

            # Determine target node for return
            target_node = return_to
            if not target_node:
                target_node = _find_node_by_agent(nodes, "DEV")
            stage_log.return_target_node_id = target_node

            if target_node:
                # Reset target stage to pending
                await db.execute(
                    update(PipelineStageLog).where(
                        PipelineStageLog.run_id == run.id,
                        PipelineStageLog.node_id == target_node,
                    ).values(status="pending", started_at=None, completed_at=None)
                )
                run.current_node_id = target_node
                run.current_stage = nodes.get(target_node, {}).get("data", {}).get("agent", "")
                response["next_node_id"] = target_node
                response["returned"] = True
            else:
                stage_log.status = "failed"
                stage_log.error_message = "No return target found"

        elif status == "completed":
            stage_log.status = "completed"

            # Find next node
            next_node_id = _get_next_node(nodes, node_id)

            if next_node_id:
                response["next_node_id"] = next_node_id

                # If auto_advance, execute next stage (with depth limit)
                if run.auto_advance:
                    # Count completed stages as depth check
                    from sqlalchemy import func as sa_func
                    completed_count = (await db.execute(
                        select(sa_func.count(PipelineStageLog.id)).where(
                            PipelineStageLog.run_id == run.id,
                            PipelineStageLog.status == "completed",
                        )
                    )).scalar() or 0
                    if completed_count >= MAX_AUTO_ADVANCE_DEPTH:
                        logger.warning("Auto-advance depth limit reached (%d), stopping", MAX_AUTO_ADVANCE_DEPTH)
                        response["auto_advance_stopped"] = True
                        response["next_stage"] = nodes.get(next_node_id, {}).get("data", {}).get("agent", "")
                    else:
                        await db.commit()
                        next_stage_log = await self.execute_stage(db, run, next_node_id, run.started_by)
                        response["auto_advanced"] = True
                        response["next_stage"] = next_stage_log.stage
            else:
                # Last stage completed — pipeline done
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                backlog_item.status = pipeline_def.final_task_status or "done"
                response["pipeline_status"] = "completed"

                # Handle merge/PR if configured
                if repo_path and run.git_branch:
                    try:
                        merge_result = await git_manager.merge_to_base(
                            repo_path=repo_path,
                            branch_name=run.git_branch,
                            base_branch=project.base_branch or "main",
                            strategy=project.merge_strategy or "merge",
                        )
                        response["merge"] = merge_result
                    except GitError as e:
                        logger.warning("Post-pipeline merge failed: %s", e)
                        response["merge_error"] = str(e)

        elif status == "failed":
            stage_log.status = "failed"
            stage_log.error_message = message
            run.status = "failed"
            response["pipeline_status"] = "failed"

        await db.commit()

        logger.info(
            "Stage completed: run=%s node=%s status=%s next=%s",
            run.id, node_id, status, response.get("next_node_id"),
        )
        return response

    async def advance_pipeline(
        self,
        db: AsyncSession,
        pipeline_run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict:
        """Advance to the next stage. Called by 'Next' button."""
        run = await db.get(PipelineRun, pipeline_run_id)
        if not run:
            raise PipelineError("Pipeline run not found")
        if run.status != "running":
            raise PipelineError(f"Pipeline is {run.status}")

        pipeline_def = await db.get(PipelineDefinition, run.pipeline_def_id)
        nodes = _extract_graph_data(pipeline_def.graph_json)

        # Find the next pending node after current
        next_node_id = _get_next_node(nodes, run.current_node_id)
        if not next_node_id:
            # Maybe it's a return — find the current node if it's pending
            result = await db.execute(
                select(PipelineStageLog).where(
                    PipelineStageLog.run_id == run.id,
                    PipelineStageLog.node_id == run.current_node_id,
                    PipelineStageLog.status == "pending",
                )
            )
            if result.scalar_one_or_none():
                next_node_id = run.current_node_id
            else:
                raise PipelineError("No next stage to advance to")

        stage_log = await self.execute_stage(db, run, next_node_id, user_id)
        return {
            "node_id": next_node_id,
            "stage": stage_log.stage,
            "status": "running",
        }

    async def cancel_pipeline(
        self,
        db: AsyncSession,
        pipeline_run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Cancel a running pipeline."""
        run = await db.get(PipelineRun, pipeline_run_id)
        if not run:
            raise PipelineError("Pipeline run not found")

        project = await db.get(Project, run.project_id)

        # Kill terminal session (use the user who started the pipeline, not the canceller)
        await terminal_manager.kill_session(run.started_by, project.id)

        # Update status
        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)

        # Mark running stages as failed
        await db.execute(
            update(PipelineStageLog).where(
                PipelineStageLog.run_id == run.id,
                PipelineStageLog.status == "running",
            ).values(status="failed", error_message="Pipeline cancelled")
        )

        await db.commit()
        logger.info("Pipeline cancelled: run=%s", run.id)

    async def get_run_status(
        self,
        db: AsyncSession,
        pipeline_run_id: uuid.UUID,
    ) -> dict:
        """Get full pipeline run status with all stage logs."""
        run = await db.get(PipelineRun, pipeline_run_id)
        if not run:
            raise PipelineError("Pipeline run not found")

        result = await db.execute(
            select(PipelineStageLog).where(
                PipelineStageLog.run_id == run.id,
            ).order_by(PipelineStageLog.node_id)
        )
        stages = result.scalars().all()

        return {
            "id": str(run.id),
            "status": run.status,
            "current_stage": run.current_stage,
            "current_node_id": run.current_node_id,
            "git_branch": run.git_branch,
            "auto_advance": run.auto_advance,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "stages": [
                {
                    "node_id": s.node_id,
                    "stage": s.stage,
                    "node_type": s.node_type,
                    "status": s.status,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                    "output_summary": s.output_summary,
                    "error_message": s.error_message,
                    "return_reason": s.return_reason,
                }
                for s in stages
            ],
        }


# Singleton
pipeline_engine = PipelineEngine()
