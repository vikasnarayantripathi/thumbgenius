def get_prompt(topic: str, niche: str) -> str:
    niche_context = {
        "tech": "Use comparison framing, product names, blue/white palette. Numbers matter.",
        "finance": "Use urgency, money amounts, before/after framing. Red/black palette.",
        "fitness": "Transformation language, body stats, time frames. Before/after structure.",
        "gaming": "Use character names, high contrast, exclamation energy. Dark backgrounds.",
        "food": "Appetite appeal, recipe names, warm colours. Close-up food imagery.",
        "travel": "Location names, wanderlust triggers, vivid scenery descriptions.",
        "education": "Clarity, step-by-step promise, clean design. Authority tone.",
        "motivation": "Emotional language, personal story hook, bold statement thumbnails.",
        "beauty": "Before/after, product reveals, warm lighting. Transformation focus.",
        "entertainment": "Reaction energy, pop culture references, relatable expressions."
    }

    context = niche_context.get(niche, "General YouTube audience. Focus on curiosity and value.")

    return f"""You are a YouTube growth expert who has studied 10 million viral videos.
Niche context: {context}
Video topic: {topic}

Respond ONLY in this exact JSON format, nothing else:
{{
    "titles": [
        "Title 1 - curiosity driven",
        "Title 2 - transformation/result",
        "Title 3 - shock/surprise",
        "Title 4 - number/list format",
        "Title 5 - question format"
    ],
    "thumbnail": {{
        "background": "describe background scene or color",
        "face_expression": "expression to show or none",
        "text_overlay": "max 4 bold words",
        "emotion_trigger": "curiosity/shock/urgency/value/fear",
        "ctr_score": 8.5,
        "why_it_works": "one sentence explanation"
    }},
    "hook_script": "First 15-20 seconds script that stops the scroll...",
    "niche_tip": "one specific tip for {niche} creators about this topic"
}}"""