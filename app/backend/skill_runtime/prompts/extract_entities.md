Extract named entities from the text. If entity_types are provided, only extract
those types. Never invent entities not present in the text.

Entity types: {entity_types}
Text: {text}

Return ONLY JSON:
{"entities": [{"name": "...", "type": "..."}], "evidence": []}
