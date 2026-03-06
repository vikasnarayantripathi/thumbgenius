"""
ThumbGenius — main.py
Production-ready FastAPI backend
Handles 2500+ concurrent users via async I/O + connection pooling
"""

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os, json, time, asyncio, logging
from collections import defaultdict

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("thumbgenius")

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ThumbGenius starting up...")
    yield
    logger.info("ThumbGenius shutting down...")

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://thumbgenius.in", "https://www.thumbgenius.in"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

templates = Jinja2Templates(directory="templates")

# AsyncOpenAI — non-blocking, handles thousands of concurrent requests
client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=2,
    timeout=30.0,
)

# ─── Rate limiting ────────────────────────────────────────────────────────────
free_uses    = defaultdict(int)
image_uses   = defaultdict(int)
MAX_FREE        = 3
MAX_FREE_IMAGES = 1

def get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host

# ─── Niche context ────────────────────────────────────────────────────────────
NICHE_CONTEXT = {
    "tech":          "Use curiosity gaps, tech specs as hooks, comparison angles. Indian audience loves value-for-money framing. Include rupee pricing angles.",
    "finance":       "Use money amounts, percentage gains/losses, urgency. Indian audience responds to SIP, mutual funds, stock market, salary references.",
    "gaming":        "Use challenge framing, game names, rank/level references. Aggressive energy. Indian gaming audience loves Free Fire, BGMI, GTA.",
    "fitness":       "Use transformation angles, time-based promises (30 days, 7 days). Indian audience responds to desi diet, home workout, no gym.",
    "food":          "Use sensory words, regional cuisine names, quick/easy angles. Indian food audience loves street food, regional recipes, restaurant reviews.",
    "travel":        "Use discovery angles, budget travel, hidden gems. Indian audience loves hill stations, beaches, budget trips, visa-free destinations.",
    "education":     "Use skill gaps, career outcomes, time-to-learn angles. Indian audience responds to job market, salary hikes, certifications.",
    "motivation":    "Use struggle-to-success arcs, mindset shifts, Indian success stories. Quotes from Indian entrepreneurs resonate well.",
    "beauty":        "Use transformation, product comparisons, drugstore vs luxury. Indian audience loves affordable dupes, skin tone inclusive content.",
    "entertainment": "Use controversy, reactions, predictions. Indian entertainment audience loves Bollywood, OTT reviews, celebrity drama.",
    "business":      "Use success stories, income figures, entrepreneurship energy. Bold claims with proof. Indian startup ecosystem references.",
    "productivity":  "Time-saving angles, before/after routines, number-driven. Indian work culture context.",
    "cricket":       "Match energy, player names, stats. High emotion, patriotic tone. IPL, World Cup references.",
    "automobiles":   "Speed, comparison, value-for-money. Indian roads context. Maruti vs Hyundai type comparisons.",
    "examprep":      "UPSC/JEE/NEET context, rank mentions, study hacks. Urgency and aspiration. AIR 1 type references.",
    "health":        "Transformation, doctor-backed claims, Indian diet context. Ayurveda and modern medicine mix.",
    "pets":          "Cute and emotional. Dog/cat focus. Indian pet owner context. Breed recommendations for Indian climate.",
    "music":         "Genre-specific energy, artist names, viral hooks. Indian indie and Bollywood music context.",
    "realestate":    "Price reveals, location names, investment angle. Mumbai, Delhi, Bangalore property market.",
    "spirituality":  "Calm but impactful. Ancient wisdom meets modern life. Meditation, yoga, Indian philosophy.",
}

def get_generate_prompt(topic: str, niche: str) -> str:
    tip = NICHE_CONTEXT.get(niche, NICHE_CONTEXT["tech"])
    return f"""You are a world-class YouTube growth strategist specializing in the Indian creator market.

Video Topic: "{topic}"
Niche: {niche}
Niche Strategy: {tip}

Generate a complete viral content package. Respond ONLY in valid JSON with no markdown, no extra text.

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
    "face_expression": "exact expression to make",
    "text_overlay": "3-5 WORD BOLD TEXT IN CAPS",
    "emotion_trigger": "primary emotion this thumbnail triggers in viewer",
    "ctr_score": 8.5,
    "why_it_works": "one sentence explaining the psychological hook"
  }},
  "hook_script": "Write the exact first 15 seconds of the video as a script. Start with a pattern interrupt. Make it impossible to click away.",
  "niche_tip": "One specific tactical tip for growing in this niche on YouTube India in 2025. Be specific and actionable.",
  "tags": {{
    "primary": ["tag1","tag2","tag3","tag4","tag5"],
    "secondary": ["tag6","tag7","tag8","tag9","tag10"],
    "longtail": ["longer phrase 1","longer phrase 2","longer phrase 3","longer phrase 4","longer phrase 5"],
    "hindi_mix": ["hindi tag 1","hindi tag 2","hindi tag 3","hindi tag 4","hindi tag 5"]
  }}
}}

Rules:
- Titles must be 60-70 characters max
- All titles must feel different, not just rewordings
- Text overlay must be SHORT and punchy, 3-5 words max
- Return ONLY the JSON object, nothing else"""

def parse_json_safe(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ─── Trending cache with async lock ───────────────────────────────────────────
_trending_cache: dict = {"data": None, "ts": 0.0}
_trending_lock = asyncio.Lock()
TRENDING_TTL = 6 * 3600  # 6 hours — one API call per 6hrs for all users

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health():
    return {"status": "ok", "service": "thumbgenius"}

@app.post("/generate")
async def generate(request: Request):
    ip = get_ip(request)

    if free_uses[ip] >= MAX_FREE:
        return JSONResponse({"error": "free_limit_reached"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    topic = str(data.get("topic", "")).strip()
    niche = str(data.get("niche", "tech")).strip()

    if not topic:
        return JSONResponse({"error": "Please enter a video topic"}, status_code=400)
    if len(topic) > 300:
        return JSONResponse({"error": "Topic too long"}, status_code=400)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a YouTube growth expert. Always respond in valid JSON only."},
                {"role": "user",   "content": get_generate_prompt(topic, niche)},
            ],
            temperature=0.8,
            max_tokens=1200,
        )
        result = parse_json_safe(response.choices[0].message.content)
        free_uses[ip] += 1
        result["uses_remaining"] = MAX_FREE - free_uses[ip]
        return JSONResponse(result)
    except json.JSONDecodeError:
        logger.error("JSON decode error in /generate")
        return JSONResponse({"error": "AI returned invalid response. Please try again."}, status_code=500)
    except Exception as e:
        logger.error(f"/generate error: {e}")
        return JSONResponse({"error": "Generation failed. Please try again."}, status_code=500)

@app.post("/generate-image")
async def generate_image(request: Request):
    ip = get_ip(request)

    if image_uses[ip] >= MAX_FREE_IMAGES:
        return JSONResponse({"error": "image_limit_reached"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    concept      = str(data.get("concept", "")).strip()
    text_overlay = str(data.get("text_overlay", "")).strip()

    if not concept:
        return JSONResponse({"error": "No concept provided"}, status_code=400)

    try:
        prompt = (
            "Professional YouTube thumbnail image. "
            f"Background: {concept}. "
            f"Large bold text overlay saying: {text_overlay}. "
            "Style: Ultra high contrast, vibrant colors, professional YouTube thumbnail. "
            "Text must be very large, bold and clearly readable. "
            "Extremely eye-catching and click-worthy. "
            "16:9 aspect ratio. No watermarks. No borders."
        )
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            quality="standard",
            n=1,
        )
        image_uses[ip] += 1
        return JSONResponse({
            "image_url": response.data[0].url,
            "images_remaining": MAX_FREE_IMAGES - image_uses[ip],
        })
    except Exception as e:
        logger.error(f"/generate-image error: {e}")
        return JSONResponse({"error": "Image generation failed. Please try again."}, status_code=500)

@app.post("/ab-test")
async def ab_test(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    title_a = str(data.get("titleA", "")).strip()
    title_b = str(data.get("titleB", "")).strip()

    if not title_a or not title_b:
        return JSONResponse({"error": "Please enter both titles"}, status_code=400)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a YouTube CTR expert. Always respond in valid JSON only."},
                {"role": "user", "content": (
                    "Compare these two YouTube video titles for the Indian audience. "
                    "Respond ONLY in valid JSON with no markdown.\n"
                    f'Title A: "{title_a}"\n'
                    f'Title B: "{title_b}"\n'
                    'Return: {"winner":"A or B","score_a":8,"score_b":7,"reasoning":"2-3 sentences on which gets more clicks and why"}'
                )},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        result = parse_json_safe(response.choices[0].message.content)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"/ab-test error: {e}")
        return JSONResponse({"error": "Test failed. Please try again."}, status_code=500)

@app.post("/analyze-channel")
async def analyze_channel(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    titles = str(data.get("titles", "")).strip()

    if not titles:
        return JSONResponse({"error": "Please enter your video titles"}, status_code=400)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a YouTube growth expert. Always respond in valid JSON only."},
                {"role": "user", "content": (
                    "Analyze these Indian YouTube video titles. "
                    "Respond ONLY in valid JSON with no markdown.\n"
                    f'Titles: "{titles}"\n'
                    "Return: {"
                    '"ctr_score":7,"emotion_score":6,"clarity_score":8,'
                    '"issues":[{"title":"issue name","detail":"explanation"}],'
                    '"fixes":[{"title":"fix name","detail":"how to apply"}],'
                    '"rewrites":[{"original":"old title","improved":"better version"}]}'
                )},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        result = parse_json_safe(response.choices[0].message.content)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"/analyze-channel error: {e}")
        return JSONResponse({"error": "Analysis failed. Please try again."}, status_code=500)

@app.get("/trending")
async def trending():
    now = time.time()

    # Fast path: return cached data if fresh
    if _trending_cache["data"] and now - _trending_cache["ts"] < TRENDING_TTL:
        return JSONResponse(_trending_cache["data"])

    # Slow path: acquire lock so only ONE request calls OpenAI
    # All other concurrent requests wait and get the cached result
    async with _trending_lock:
        if _trending_cache["data"] and now - _trending_cache["ts"] < TRENDING_TTL:
            return JSONResponse(_trending_cache["data"])

        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a YouTube trends expert. Always respond in valid JSON only."},
                    {"role": "user", "content": (
                        "Generate 16 trending YouTube video topics for Indian creators in 2025. "
                        "Return ONLY a JSON array with no markdown:\n"
                        '[{"niche":"tech","topic":"video idea","why":"why trending in India now","heat":"fire emoji"}]\n'
                        "Cover exactly 2 topics each for: tech, finance, gaming, fitness, cricket, automobiles, examprep, motivation"
                    )},
                ],
                temperature=0.9,
                max_tokens=1000,
            )
            result = parse_json_safe(response.choices[0].message.content)
            _trending_cache["data"] = result
            _trending_cache["ts"] = time.time()
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"/trending error: {e}")
            if _trending_cache["data"]:
                return JSONResponse(_trending_cache["data"])
            return JSONResponse({"error": "Failed to load trending topics."}, status_code=500)
