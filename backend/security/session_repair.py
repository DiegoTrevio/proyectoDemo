"""Session Repair — validates and repairs context in long-running sessions.

In sessions exceeding 200K+ tokens, context degrades. Session Repair runs
7 validation phases every 10 iterations and compacts context when needed.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("agentos.security.session_repair")

REPAIR_INTERVAL = 10  # Run every N iterations


@dataclass
class RepairResult:
    """Result of a session repair cycle."""
    phase_results: dict[str, bool] = field(default_factory=dict)
    issues_found: list[str] = field(default_factory=list)
    repairs_applied: list[str] = field(default_factory=list)
    context_compacted: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def healthy(self) -> bool:
        return len(self.issues_found) == 0


class SessionRepair:
    """Validates and repairs agent session state."""

    def __init__(self):
        self._action_history: dict[str, list[str]] = {}  # task_id -> [actions]

    def should_run(self, iteration: int) -> bool:
        """Check if repair should run at this iteration."""
        return iteration > 0 and iteration % REPAIR_INTERVAL == 0

    def run_repair(self, state: dict) -> RepairResult:
        """Run all 7 repair phases on the agent state.

        Args:
            state: The AgentState dict from the orchestrator.

        Returns:
            RepairResult with findings and repairs.
        """
        result = RepairResult()
        task_id = state.get("task_id", "")

        # Phase 1: Todo/plan consistency
        result.phase_results["plan_consistency"] = self._check_plan_consistency(state, result)

        # Phase 2: Contradiction detection
        result.phase_results["contradictions"] = self._check_contradictions(state, result)

        # Phase 3: Error context preservation
        result.phase_results["error_context"] = self._check_error_context(state, result)

        # Phase 4: Personality drift detection
        result.phase_results["personality_drift"] = self._check_personality_drift(state, result)

        # Phase 5: Memory context integrity
        result.phase_results["memory_integrity"] = self._check_memory_integrity(state, result)

        # Phase 6: Loop detection
        result.phase_results["loop_detection"] = self._check_loops(state, result, task_id)

        # Phase 7: Goal drift detection
        result.phase_results["goal_drift"] = self._check_goal_drift(state, result)

        # Apply compaction if issues found
        if len(result.issues_found) >= 3:
            self._compact_context(state, result)

        if result.issues_found:
            logger.warning(
                "Session repair for %s found %d issues: %s",
                task_id, len(result.issues_found), result.issues_found,
            )
        else:
            logger.debug("Session repair for %s: all healthy", task_id)

        return result

    def _check_plan_consistency(self, state: dict, result: RepairResult) -> bool:
        """Phase 1: Verify plan is consistent with results."""
        plan = state.get("plan", [])
        results = state.get("results", [])

        if not plan:
            return True

        completed_steps = {r.get("step") for r in results if r.get("success")}
        plan_completed = {s["step"] for s in plan if s.get("status") == "completed"}

        # Check for steps marked completed in plan but missing from results
        orphans = plan_completed - completed_steps
        if orphans:
            result.issues_found.append(
                f"Plan has {len(orphans)} steps marked completed but no results: {orphans}"
            )
            # Repair: reset orphan steps to pending
            for step in plan:
                if step["step"] in orphans:
                    step["status"] = "pending"
            result.repairs_applied.append("Reset orphan completed steps to pending")
            return False

        return True

    def _check_contradictions(self, state: dict, result: RepairResult) -> bool:
        """Phase 2: Detect contradictions in results history."""
        results = state.get("results", [])
        if len(results) < 2:
            return True

        # Check for same step with contradictory outcomes
        step_outcomes: dict[int, list[bool]] = {}
        for r in results:
            step = r.get("step", 0)
            step_outcomes.setdefault(step, []).append(r.get("success", False))

        for step, outcomes in step_outcomes.items():
            if True in outcomes and False in outcomes:
                result.issues_found.append(
                    f"Step {step} has contradictory outcomes (both success and failure)"
                )
                return False

        return True

    def _check_error_context(self, state: dict, result: RepairResult) -> bool:
        """Phase 3: Verify errors are preserved in context."""
        errors = state.get("errors", [])
        if not errors:
            return True

        # Check that error list hasn't been truncated unexpectedly
        failed_results = [r for r in state.get("results", []) if not r.get("success")]
        if len(failed_results) > len(errors) + 2:
            result.issues_found.append(
                f"Error context may be incomplete: {len(failed_results)} failures but only {len(errors)} errors"
            )
            return False

        return True

    def _check_personality_drift(self, state: dict, result: RepairResult) -> bool:
        """Phase 4: Detect personality drift in agent behavior.

        Checks if the agent is deviating from its expected behavior patterns.
        """
        # In a full implementation, this would compare recent outputs against
        # baseline behavior patterns. For now, check structural integrity.
        final_output = state.get("final_output", "")
        goal = state.get("goal", "")

        if final_output and goal:
            # Check if output is suspiciously unrelated to goal
            goal_words = set(goal.lower().split()[:10])
            output_words = set(final_output.lower().split()[:50])

            # If the first 10 goal words have zero overlap with first 50 output words
            overlap = goal_words & output_words
            common_words = {"the", "a", "an", "is", "to", "of", "and", "in", "for", "that", "it", "with"}
            meaningful_overlap = overlap - common_words

            if len(goal_words - common_words) > 3 and len(meaningful_overlap) == 0:
                result.issues_found.append("Potential personality drift: output seems unrelated to goal")
                return False

        return True

    def _check_memory_integrity(self, state: dict, result: RepairResult) -> bool:
        """Phase 5: Verify memory_context hasn't been corrupted."""
        memory = state.get("memory_context", {})

        if not isinstance(memory, dict):
            result.issues_found.append(f"memory_context is {type(memory).__name__}, expected dict")
            state["memory_context"] = {}
            result.repairs_applied.append("Reset corrupted memory_context to empty dict")
            return False

        return True

    def _check_loops(self, state: dict, result: RepairResult, task_id: str) -> bool:
        """Phase 6: Detect repeated actions (same action > 3 times)."""
        plan = state.get("plan", [])
        results = state.get("results", [])

        # Track action patterns
        actions = self._action_history.setdefault(task_id, [])
        for r in results[len(actions):]:
            actions.append(f"{r.get('agent', '')}:{r.get('step', '')}")

        # Check for loops: same pattern repeated > 3 times
        if len(actions) >= 6:
            recent = actions[-6:]
            # Check pairs
            for i in range(len(recent) - 2):
                pattern = recent[i]
                count = sum(1 for a in recent if a == pattern)
                if count >= 3:
                    result.issues_found.append(
                        f"Loop detected: action '{pattern}' repeated {count} times in last 6 actions"
                    )
                    return False

        return True

    def _check_goal_drift(self, state: dict, result: RepairResult) -> bool:
        """Phase 7: Validate the original goal hasn't been deviated from."""
        goal = state.get("goal", "")
        plan = state.get("plan", [])

        if not goal or not plan:
            return True

        # Check that plan descriptions are related to the goal
        goal_lower = goal.lower()
        unrelated = 0
        for step in plan:
            desc = step.get("description", "").lower()
            # Very basic relevance check — share at least one meaningful word
            goal_words = {w for w in goal_lower.split() if len(w) > 3}
            desc_words = {w for w in desc.split() if len(w) > 3}
            if goal_words and desc_words and not (goal_words & desc_words):
                unrelated += 1

        if unrelated > len(plan) * 0.6:
            result.issues_found.append(
                f"Goal drift detected: {unrelated}/{len(plan)} plan steps seem unrelated to goal"
            )
            return False

        return True

    def _compact_context(self, state: dict, result: RepairResult) -> None:
        """Compact context by keeping only critical information."""
        results = state.get("results", [])

        if len(results) > 20:
            # Keep first 3 and last 10, summarize the middle
            kept = results[:3] + results[-10:]
            state["results"] = kept
            result.repairs_applied.append(
                f"Compacted results from {len(results)} to {len(kept)} (kept first 3 + last 10)"
            )
            result.context_compacted = True

        errors = state.get("errors", [])
        if len(errors) > 20:
            # Keep last 10 errors
            state["errors"] = errors[-10:]
            result.repairs_applied.append(
                f"Compacted errors from {len(errors)} to 10 (kept last 10)"
            )
            result.context_compacted = True


# Singleton
session_repair = SessionRepair()
