from __future__ import annotations
import datetime
import traceback
from functools import wraps
from orchestration.state import EngagementState, AgentRun


def agent_step(agent_name: str):
    """Wrap an agent fn(state, ctx)->state with status/timing/error capture,
    so a single agent failing never crashes the whole graph — it's recorded
    and the pipeline continues with whatever state exists so far."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(state: EngagementState, ctx, *args, **kwargs) -> EngagementState:
            run = AgentRun(name=agent_name, status="RUNNING", started_at=_now())
            state.agent_runs[agent_name] = run
            try:
                state = fn(state, ctx, *args, **kwargs)
                run.status = "DONE"
            except Exception as e:
                run.status = "FAILED"
                run.errors.append(f"{type(e).__name__}: {e}")
                run.warnings.append("Agent failed; downstream agents will use partial/default data.")
                traceback.print_exc()
            run.ended_at = _now()
            state.agent_runs[agent_name] = run
            return state

        return wrapper

    return decorator


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def set_summary(state: EngagementState, agent_name: str, summary: str, sources: list[str] | None = None, tools: list[str] | None = None):
    run = state.agent_runs.get(agent_name)
    if run:
        run.reasoning_summary = summary
        if sources:
            run.sources_used = sources
        if tools:
            run.tools_used = tools
