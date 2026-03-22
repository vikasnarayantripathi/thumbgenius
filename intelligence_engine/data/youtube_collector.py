import asyncio
from datetime import datetime, timezone
from googleapiclient.discovery import build
from intelligence_engine.config import YOUTUBE_API_KEY, TRACKED_NICHES
from intelligence_engine import database

def _build_client():
    return build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

def _hours_since(published_str: str) -> float:
    published = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    return max((now - published).total_seconds() / 3600, 1.0)

def _fetch_trending_sync(niche: str, max_results: int = 20):
    youtube = _build_client()
    yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()

    search_resp = youtube.search().list(
        q=niche,
        type='video',
        order='viewCount',
        publishedAfter=yesterday,
        part='snippet',
        maxResults=max_results
    ).execute()

    video_ids = [item['id']['videoId'] for item in search_resp.get('items', [])]
    if not video_ids:
        return []

    stats_resp = youtube.videos().list(
        id=','.join(video_ids),
        part='statistics,snippet'
    ).execute()

    results = []
    for item in stats_resp.get('items', []):
        published_str = item['snippet']['publishedAt']
        hours_old = _hours_since(published_str)
        view_count = int(item['statistics'].get('viewCount', 0))
        views_per_hour = round(view_count / hours_old, 1)

        thumbs = item['snippet'].get('thumbnails', {})
        thumbnail_url = (
            thumbs.get('maxres', thumbs.get('high', thumbs.get('default', {}))).get('url', '')
        )

        results.append({
            'niche': niche,
            'video_id': item['id'],
            'title': item['snippet']['title'],
            'channel_id': item['snippet']['channelId'],
            'view_count': view_count,
            'views_per_hour': views_per_hour,
            'thumbnail_url': thumbnail_url,
            'payload': {
                'description': item['snippet'].get('description', '')[:200],
                'tags': item['snippet'].get('tags', [])[:10],
                'published_at': published_str
            }
        })

    return sorted(results, key=lambda x: x['views_per_hour'], reverse=True)

async def fetch_and_store_niche(niche: str):
    print(f"[YouTube] Fetching trends for niche: {niche}")
    try:
        loop = asyncio.get_event_loop()
        videos = await loop.run_in_executor(None, _fetch_trending_sync, niche)

        for v in videos:
            await database.execute("""
                INSERT INTO yt_trends
                    (niche, video_id, title, channel_id, view_count, views_per_hour, thumbnail_url, payload)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT DO NOTHING
            """,
                v['niche'], v['video_id'], v['title'], v['channel_id'],
                v['view_count'], v['views_per_hour'], v['thumbnail_url'],
                str(v['payload'])
            )

        print(f"[YouTube] Stored {len(videos)} videos for '{niche}'")
        return videos
    except Exception as e:
        print(f"[YouTube] Error fetching '{niche}': {e}")
        return []

async def fetch_all_niches():
    results = {}
    for niche in TRACKED_NICHES:
        videos = await fetch_and_store_niche(niche)
        results[niche] = videos
        await asyncio.sleep(1)  # stay within API quota
    return results
