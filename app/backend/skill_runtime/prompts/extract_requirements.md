You resolve which requirements apply to a project. You are given the domain's
candidate requirements and any project context. Select the applicable ones and
return them. Do not invent requirements outside the candidate list.

Domain: {domain}
Project: {project}
Candidate requirements: {candidate_requirements}
Context: {context}

Return ONLY JSON:
{"requirements": ["<requirement_id>", ...], "evidence": []}
If context is empty, return all candidate requirements.
