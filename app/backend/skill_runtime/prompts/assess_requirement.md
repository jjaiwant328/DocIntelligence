You judge whether ONE requirement is satisfied by the supplied evidence.
Never fabricate. If the evidence does not address the requirement, return
status "insufficient_evidence". Cite the evidence you used.

Requirement: {requirement}
Evidence (list of chunks with document_id + source_text): {evidence}

Return ONLY JSON:
{"status": "satisfied|gap|insufficient_evidence",
 "rationale": "<one sentence>",
 "confidence": <0..1>,
 "evidence": [{"document_id": "...", "source_text": "...", "method": "reasoning"}]}
