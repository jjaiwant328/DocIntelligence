You produce a recommendation on whether the project can proceed, and propose
draft actions to close each gap. Keep actions concrete and few.

Risk: {risk}
Gaps: {gaps}
Requirements: {requirements}

Return ONLY JSON:
{"recommendation": "<proceed|proceed_with_conditions|hold> — <one sentence>",
 "proposed_actions": [{"action_type": "...", "description": "...", "priority": "low|medium|high"}],
 "evidence": []}
