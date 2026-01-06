"""Runtime orchestration for the travel planner workflow."""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from workflows.state import TravelPlannerState
from workflows.workflow import TravelPlannerOrchestrator, SelectionInterrupt

# Backward compatibility alias
TravelPlannerWorkflow = TravelPlannerOrchestrator


class TravelPlannerRuntime:
    """Stateful runtime used by the FastAPI service."""

    def __init__(self) -> None:
        self._workflows: Dict[str, TravelPlannerOrchestrator] = {}
        self._lock = threading.Lock()

    async def run_turn(
        self, state: Optional[TravelPlannerState], user_input: Any
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """Run one conversational turn (message or interrupt)."""

        return await asyncio.to_thread(self._run_turn_sync, state, user_input)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _run_turn_sync(
        self, state: Optional[TravelPlannerState], user_input: Any
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        if state is None:
            thread_id = str(uuid.uuid4())
            workflow = self._create_workflow(thread_id)
            new_state = workflow.initial_state(thread_id)
            new_state, interrupts = workflow.start(new_state)
            return new_state, interrupts

        workflow = self._get_or_create_workflow(state.thread_id)

        if user_input is None:
            return state, []

        if isinstance(user_input, dict):
            return workflow.handle_interrupt(state, user_input)

        message = str(user_input)
        return workflow.handle_user_message(state, message)

    def _create_workflow(self, thread_id: str) -> TravelPlannerOrchestrator:
        workflow = TravelPlannerOrchestrator()
        with self._lock:
            self._workflows[thread_id] = workflow
        return workflow

    def _get_or_create_workflow(self, thread_id: str) -> TravelPlannerOrchestrator:
        with self._lock:
            workflow = self._workflows.get(thread_id)
            if workflow is None:
                workflow = TravelPlannerOrchestrator()
                self._workflows[thread_id] = workflow
            return workflow
