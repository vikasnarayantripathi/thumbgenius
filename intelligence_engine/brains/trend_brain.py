from intelligence_engine import database

async def analyze() -> list:
    """
    Reads last 24h of yt_trends, identifies top patterns per niche,
    returns scored trend signals.
    """
    rows = await database.fetch("""
        SELECT niche, title, views_per_hour, thumbnail_url, payload
        FROM yt_trends
        WHERE fetched_at > NOW() - INTERVAL '24 hours'
        ORDER BY views_per_hour DESC
    """)

    if not rows:
        print("[TrendBrain] No data yet. Run fetch_all_niches first.")
        return []

    # Group by niche
    by_niche = {}
    for row in rows:
        n = row['niche']
        if n not in by_niche:
            by_niche[n] = []
        by_niche[n].append(dict(row))

    signals = []
    for niche, videos in by_niche.items():
        if not videos:
            continue

        top = videos[:5]
        avg_velocity = sum(v['views_per_hour'] for v in top) / len(top)

        # Pattern detection: check title keywords in top videos
        all_titles = ' '.join(v['title'].lower() for v in top)
        patterns = _detect_patterns(all_titles)

        confidence = min(95, int(50 + (avg_velocity / 1000) * 10 + len(top) * 3))

        signals.append({
            'niche': niche,
            'top_video_count': len(videos),
            'avg_velocity': round(avg_velocity, 1),
            'patterns': patterns,
            'confidence': confidence,
            'sample_titles': [v['title'] for v in top[:3]],
            'reason': f"Top {len(top)} videos averaging {avg_velocity:.0f} views/hr. Patterns: {', '.join(patterns) or 'none detected'}"
        })

    signals.sort(key=lambda x: x['confidence'], reverse=True)
    print(f"[TrendBrain] Analyzed {len(signals)} niches.")
    return signals

def _detect_patterns(text: str) -> list:
    patterns = []
    checks = {
        'number_hook':    any(w.isdigit() for w in text.split()),
        'how_to':         'how to' in text or 'tutorial' in text,
        'question_hook':  '?' in text or text.startswith('why') or text.startswith('what'),
        'face_emotion':   any(w in text for w in ['reaction', 'shocked', 'crying', 'emotional']),
        'vs_comparison':  ' vs ' in text,
        'list_format':    any(text.startswith(str(n)) for n in range(1, 20)),
    }
    for pattern, matched in checks.items():
        if matched:
            patterns.append(pattern)
    return patterns
