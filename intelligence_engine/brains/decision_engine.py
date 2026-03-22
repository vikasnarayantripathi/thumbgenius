import json
from datetime import datetime, timezone
from intelligence_engine import database
from intelligence_engine.brains import trend_brain

WEIGHTS = {
    'trend_confidence': 0.50,
    'data_volume':      0.30,
    'velocity':         0.20,
}

async def generate_suggestions() -> list:
    signals = await trend_brain.analyze()
    if not signals:
        print("[DecisionEngine] No signals to process.")
        return []

    suggestions = []
    for signal in signals:
        score = (
            signal['confidence']                       * WEIGHTS['trend_confidence'] +
            min(signal['top_video_count'] * 5, 100)   * WEIGHTS['data_volume'] +
            min(signal['avg_velocity'] / 100, 100)    * WEIGHTS['velocity']
        )
        score = int(min(score, 99))

        if score < 60:
            continue

        impact = 'high' if score >= 80 else 'medium'
        risk   = 'low'  if signal['top_video_count'] >= 10 else 'medium'

        config_patch = _build_patch(signal)

        suggestion = {
            'title':        f"Adopt '{signal['patterns'][0] if signal['patterns'] else 'trending'}' style for {signal['niche']}",
            'description':  f"Top videos in {signal['niche']} are averaging {signal['avg_velocity']:.0f} views/hr",
            'reason':       signal['reason'],
            'confidence':   score,
            'impact':       impact,
            'risk':         risk,
            'config_patch': json.dumps(config_patch),
        }

        await database.execute("""
            INSERT INTO ie_suggestions
                (title, description, reason, confidence, impact, risk, config_patch)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
        """,
            suggestion['title'], suggestion['description'], suggestion['reason'],
            suggestion['confidence'], suggestion['impact'], suggestion['risk'],
            suggestion['config_patch']
        )

        suggestions.append(suggestion)
        print(f"[DecisionEngine] Suggestion created: {suggestion['title']} (score={score})")

    return suggestions

def _build_patch(signal: dict) -> dict:
    patch = {'niche_settings': {}}
    niche = signal['niche']
    patterns = signal['patterns']

    cta_style = 'number_hook' if 'number_hook' in patterns else \
                'how_to'      if 'how_to'      in patterns else \
                'question'    if 'question_hook' in patterns else 'action_verb'

    patch['niche_settings'][niche] = {
        'cta_style':      cta_style,
        'trending_patterns': patterns[:3],
        'last_updated':   datetime.now(timezone.utc).isoformat()
    }
    return patch
