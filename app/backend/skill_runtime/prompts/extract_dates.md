Extract dates from the text and label each with its role (effective, expiry,
deadline, other). Only include dates present in the text.

Text: {text}

Return ONLY JSON:
{"dates": [{"date": "YYYY-MM-DD", "role": "..."}], "evidence": []}
