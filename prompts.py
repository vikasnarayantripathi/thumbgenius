NICHE_CONTEXT = {
    "tech": "Use curiosity gaps, tech specs as hooks, comparison angles. Indian audience loves value-for-money framing. Include ₹ pricing angles.",
    "finance": "Use money amounts, percentage gains/losses, urgency. Indian audience responds to SIP, mutual funds, stock market, salary references.",
    "gaming": "Use challenge framing, game names, rank/level references. Aggressive energy. Indian gaming audience loves Free Fire, BGMI, GTA.",
    "fitness": "Use transformation angles, time-based promises (30 days, 7 days). Indian audience responds to desi diet, home workout, no gym.",
    "food": "Use sensory words, regional cuisine names, quick/easy angles. Indian food audience loves street food, regional recipes, restaurant reviews.",
    "travel": "Use discovery angles, budget travel, hidden gems. Indian audience loves hill stations, beaches, budget trips, visa-free destinations.",
    "education": "Use skill gaps, career outcomes, time-to-learn angles. Indian audience responds to job market, salary hikes, certifications.",
    "motivation": "Use struggle-to-success arcs, mindset shifts, Indian success stories. Quotes from Indian entrepreneurs resonate well.",
    "beauty": "Use transformation, product comparisons, drugstore vs luxury. Indian audience loves affordable dupes, skin tone inclusive content.",
    "entertainment": "Use controversy, reactions, predictions. Indian entertainment audience loves Bollywood, OTT reviews, celebrity drama.",
    "business": "Use success stories, income figures, entrepreneurship energy. Bold claims with proof. Indian startup ecosystem references.",
    "productivity": "Time-saving angles, before/after routines, number-driven (5x faster, 2hrs saved). Indian work culture context.",
    "cricket": "Match energy, player names, stats, Indian audience. High emotion, patriotic tone. IPL, World Cup references.",
    "automobiles": "Speed, comparison, value-for-money. Indian roads context. Review energy. Maruti vs Hyundai type comparisons.",
    "examprep": "UPSC/JEE/NEET context, rank mentions, study hacks. Urgency and aspiration. AIR 1 type references.",
    "health": "Transformation, doctor-backed claims, Indian diet context. Before/after framing. Ayurveda and modern medicine mix.",
    "pets": "Cute + emotional. Dog/cat focus. Indian pet owner context. Breed recommendations for Indian climate.",
    "music": "Genre-specific energy, artist names, viral hooks. Emotion-forward. Indian indie and Bollywood music context.",
    "realestate": "Price reveals, location names, investment angle. Indian city context. Mumbai, Delhi, Bangalore property market.",
    "spirituality": "Calm but impactful. Ancient wisdom meets modern life. Transformation angle. Meditation, yoga, Indian philosophy."
}

def get_prompt(topic: str, niche: str) -> str:
    niche_tip = NICHE_CONTEXT.get(niche, NICHE_CONTEXT["tech"])

    return f"""You are a world-class YouTube growth strategist specializing in the Indian creator market.

Video Topic: "{topic}"
Niche: {niche}
Niche Strategy: {niche_tip}

Generate a complete viral content package. Respond ONLY in valid JSON — no markdown, no extra text.

{{
  "titles": [
    "title 1 - high curiosity gap",
    "title 2 - emotional/shock angle", 
    "title 3 - number/list format",
    "title 4 - personal story angle",
    "title 5 - controversy/challenge angle"
  ],
  "thumbnail": {{
    "background": "describe background scene, colors, key visual elements",
    "face_expression": "exact expression to make - e.g. shocked open mouth, huge smile, confused squint",
    "text_overlay": "3-5 WORD BOLD TEXT IN CAPS",
    "emotion_trigger": "primary emotion this thumbnail triggers in viewer",
    "ctr_score": 8.5,
    "why_it_works": "one sentence explaining the psychological hook"
  }},
  "hook_script": "Write the exact first 15 seconds of the video as a script. Start with a pattern interrupt. Make it impossible to click away. Write it naturally as spoken words.",
  "niche_tip": "One specific tactical tip for growing in this niche on YouTube India in 2025. Be specific and actionable.",
  "tags": {{
    "primary": ["tag1", "tag2", "tag3", "tag4", "tag5"],
    "secondary": ["tag6", "tag7", "tag8", "tag9", "tag10"],
    "longtail": ["longer phrase tag 1", "longer phrase tag 2", "longer phrase tag 3", "longer phrase tag 4", "longer phrase tag 5"],
    "hindi_mix": ["hindi or hinglish tag 1", "hindi or hinglish tag 2", "hindi or hinglish tag 3", "hindi or hinglish tag 4", "hindi or hinglish tag 5"]
  }}
}}

Rules:
- Titles must be 60-70 characters max
- All titles must feel different — different angles, not just rewordings
- Text overlay must be SHORT and punchy (3-5 words max)
- Hook script must be 2-4 sentences, spoken naturally
- Tags must be relevant to the topic AND niche
- Hindi/mix tags should include actual Hindi words or Hinglish that Indian viewers search
- Primary tags: exact match keywords (short, 1-3 words)
- Secondary tags: related broader topics
- Long-tail tags: full search phrases people type (5-8 words)
- Return ONLY the JSON object, nothing else"""
