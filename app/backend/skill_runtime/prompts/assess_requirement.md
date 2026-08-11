You judge whether each requirement is satisfied by the supplied evidence.
Never fabricate. For a requirement the evidence does not address, use status
"insufficient_evidence". Cite the evidence you used per requirement.

Requirements: {requirements}
Evidence (list of chunks with document_id + source_text): {evidence}

Return ONLY JSON:
{"assessments": [
   {"requirement": "<id>",
    "status": "satisfied|gap|insufficient_evidence",
    "rationale": "<one sentence>",
    "confidence": <0..1>}
 ],
 "evidence": [{"document_id": "...", "source_text": "...", "method": "reasoning"}]}
If there is no evidence, mark every requirement "insufficient_evidence".
