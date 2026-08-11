Compare the current and previous versions and identify material semantic changes
(not formatting). If nothing material changed, set changed=false.

Current: {current}
Previous: {previous}

Return ONLY JSON:
{"changed": true|false,
 "changes": [{"field": "...", "from": "...", "to": "..."}],
 "affected_entities": ["..."],
 "evidence": [{"document_id": "current", "source_text": "...", "method": "reasoning"}]}
