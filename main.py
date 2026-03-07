"""
ThumbGenius — main.py v4.0
YouTube Packaging Intelligence Platform
7 Modules: Packaging Assistant, Thumbnail Analyzer, CTR Prediction,
           Reverse Engineering, A/B Testing, Inspiration Library, Branding System
"""

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os, json, asyncio, logging, hashlib, hmac, secrets, base64
import httpx

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("thumbgenius")

# ─── ENV ──────────────────────────────────────────────────────────────────────
OPENAI_API_KEY           = os.getenv("OPENAI_API_KEY")
SUPABASE_URL             = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY        = os.getenv("SUPABASE_ANON_KEY")
UPSTASH_REDIS_REST_URL   = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
RAZORPAY_KEY_ID          = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET      = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET  = os.getenv("RAZORPAY_WEBHOOK_SECRET")
RAZORPAY_CREATOR_PLAN_ID = os.getenv("RAZORPAY_CREATOR_PLAN_ID")
RAZORPAY_PRO_PLAN_ID     = os.getenv("RAZORPAY_PRO_PLAN_ID")
RESEND_API_KEY           = os.getenv("RESEND_API_KEY")
APP_URL                  = os.getenv("APP_URL", "https://thumbgenius.in")
FROM_EMAIL               = os.getenv("FROM_EMAIL", "hello@thumbgenius.in")

PLAN_LIMITS = {
    "free":    {"generations": 3,  "images": 1,  "thumb_analysis": 1,  "reverse": 2,  "ctr_predict": 0,  "ab_tests": 3},
    "creator": {"generations": 100,"images": 20, "thumb_analysis": 50, "reverse": 25, "ctr_predict": 30, "ab_tests": 20},
    "pro":     {"generations": 300,"images": 50, "thumb_analysis": 999,"reverse": 999,"ctr_predict": 999,"ab_tests": 999},
}
ADMIN_CODES = {"VIKAS2025": {"plans": ["creator", "pro"]}}

def is_admin(code: str) -> bool:
    return code.upper() in ADMIN_CODES

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ThumbGenius v4.0 — Packaging Intelligence Platform starting...")
    yield

app = FastAPI(lifespan=lifespan)

# ─── CSP Middleware ───────────────────────────────────────────────────────────
class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://checkout.razorpay.com https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https://oaidalleapiprodscus.blob.core.windows.net "
                "https://*.openai.com https://*.blob.core.windows.net; "
            "connect-src 'self' https://api.openai.com https://api.razorpay.com "
                "https://lumberjack.razorpay.com https://jfestnbagyjrpoczhxbw.supabase.co; "
            "frame-src https://api.razorpay.com https://checkout.razorpay.com; "
            "object-src 'none';"
        )
        return response

app.add_middleware(CSPMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://thumbgenius.in", "https://www.thumbgenius.in"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-User-Email", "X-Admin-Code"],
)

templates = Jinja2Templates(directory="templates")
client    = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=2, timeout=45.0)

# ══════════════════════════════════════════════════════════════════════════════
# INFRASTRUCTURE — Redis, Supabase, Helpers
# ══════════════════════════════════════════════════════════════════════════════

async def redis_get(key):
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            r = await h.get(f"{UPSTASH_REDIS_REST_URL}/get/{key}",
                            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
            return r.json().get("result")
    except Exception as e:
        logger.warning(f"Redis GET error: {e}"); return None

async def redis_set(key, value, ex=None):
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            url = f"{UPSTASH_REDIS_REST_URL}/set/{key}/{value}"
            if ex: url += f"/ex/{ex}"
            await h.get(url, headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
    except Exception as e:
        logger.warning(f"Redis SET error: {e}")

async def redis_incr(key):
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            r = await h.get(f"{UPSTASH_REDIS_REST_URL}/incr/{key}",
                            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
            return r.json().get("result", 1)
    except Exception as e:
        logger.warning(f"Redis INCR error: {e}"); return 1

async def redis_expire(key, seconds):
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            await h.get(f"{UPSTASH_REDIS_REST_URL}/expire/{key}/{seconds}",
                        headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
    except Exception as e:
        logger.warning(f"Redis EXPIRE error: {e}")

SB_HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

async def sb_get_user(email):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}&select=*", headers=SB_HEADERS)
            d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_user: {e}"); return None

async def sb_upsert_user(email, data):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post(f"{SUPABASE_URL}/rest/v1/users",
                         headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"},
                         json={"email": email, **data})
    except Exception as e:
        logger.error(f"sb_upsert_user: {e}")

async def sb_update_user(email, data):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.patch(f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}", headers=SB_HEADERS, json=data)
    except Exception as e:
        logger.error(f"sb_update_user: {e}")

async def sb_get_user_by_token(token):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(f"{SUPABASE_URL}/rest/v1/users?activation_token=eq.{token}&select=*", headers=SB_HEADERS)
            d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_by_token: {e}"); return None

async def sb_get_user_by_subscription(sub_id):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(f"{SUPABASE_URL}/rest/v1/users?razorpay_subscription_id=eq.{sub_id}&select=*", headers=SB_HEADERS)
            d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_by_sub: {e}"); return None

# Brand Kit helpers
async def sb_get_brand_kit(email):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(f"{SUPABASE_URL}/rest/v1/brand_kits?email=eq.{email}&select=*", headers=SB_HEADERS)
            d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_brand_kit: {e}"); return None

async def sb_save_brand_kit(email, kit_data):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post(f"{SUPABASE_URL}/rest/v1/brand_kits",
                         headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"},
                         json={"email": email, "kit_data": json.dumps(kit_data)})
    except Exception as e:
        logger.error(f"sb_save_brand_kit: {e}")

# Inspiration saves
async def sb_save_inspiration(email, item):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post(f"{SUPABASE_URL}/rest/v1/inspiration_saves",
                         headers=SB_HEADERS,
                         json={"email": email, **item})
    except Exception as e:
        logger.error(f"sb_save_inspiration: {e}")

async def sb_get_inspirations(email):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(f"{SUPABASE_URL}/rest/v1/inspiration_saves?email=eq.{email}&select=*&order=created_at.desc", headers=SB_HEADERS)
            return r.json() or []
    except Exception as e:
        logger.error(f"sb_get_inspirations: {e}"); return []

async def get_user_plan(email):
    if not email:
        return {"plan": "free", "generations_used": 0, "images_used": 0,
                "thumb_analysis_used": 0, "reverse_used": 0, "ctr_predict_used": 0, "ab_tests_used": 0}
    cache_key = f"plan:{email}"
    cached = await redis_get(cache_key)
    if cached:
        try: return json.loads(cached)
        except: pass
    user = await sb_get_user(email)
    if not user:
        return {"plan": "free", "generations_used": 0, "images_used": 0,
                "thumb_analysis_used": 0, "reverse_used": 0, "ctr_predict_used": 0, "ab_tests_used": 0}
    plan_data = {
        "plan": user.get("plan", "free"),
        "generations_used":    user.get("generations_used", 0),
        "images_used":         user.get("images_used", 0),
        "thumb_analysis_used": user.get("thumb_analysis_used", 0),
        "reverse_used":        user.get("reverse_used", 0),
        "ctr_predict_used":    user.get("ctr_predict_used", 0),
        "ab_tests_used":       user.get("ab_tests_used", 0),
        "is_active":           user.get("is_active", False),
    }
    await redis_set(cache_key, json.dumps(plan_data), ex=300)
    return plan_data

async def invalidate_plan_cache(email):
    await redis_set(f"plan:{email}", "", ex=1)

def get_ip(request):
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else request.client.host

def get_fingerprint(request):
    return hashlib.md5(f"{get_ip(request)}{request.headers.get('User-Agent','')[:50]}".encode()).hexdigest()[:16]

async def check_free_limit(request, key_type="free"):
    count = await redis_get(f"{key_type}:{get_fingerprint(request)}")
    return int(count) if count else 0

async def increment_free_limit(request, key_type="free"):
    key = f"{key_type}:{get_fingerprint(request)}"
    count = await redis_incr(key)
    if count == 1: await redis_expire(key, 30 * 24 * 3600)

def parse_json_safe(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())

async def send_magic_link(email, token, plan):
    activation_url = f"{APP_URL}/activate?token={token}"
    plan_name = "Creator" if plan == "creator" else "Pro"
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post("https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={
                    "from": f"ThumbGenius <{FROM_EMAIL}>",
                    "to": [email],
                    "subject": f"🎉 Activate your ThumbGenius {plan_name} Plan",
                    "html": f"""<div style="font-family:Arial;max-width:600px;margin:0 auto;background:#02020A;color:#fff;padding:40px;border-radius:12px;">
                        <h1 style="color:#FDE036">ThumbGenius</h1>
                        <p style="color:#aaa">YouTube Packaging Intelligence Platform</p>
                        <h2>Welcome to {plan_name} Plan! 🚀</h2>
                        <p style="color:#ccc">Click below to activate your account.</p>
                        <a href="{activation_url}" style="display:inline-block;background:#FDE036;color:#02020A;font-weight:bold;font-size:18px;padding:16px 40px;border-radius:8px;text-decoration:none;margin:24px 0;">Activate My Account →</a>
                        <p style="color:#666;font-size:14px">This link expires in 24 hours.</p>
                        <p style="color:#444;font-size:12px">ThumbGenius · thumbgenius.in</p>
                    </div>"""
                })
        logger.info(f"Magic link sent to {email}")
    except Exception as e:
        logger.error(f"Email send error: {e}")

async def create_razorpay_subscription(plan, email):
    plan_id = RAZORPAY_CREATOR_PLAN_ID if plan == "creator" else RAZORPAY_PRO_PLAN_ID
    try:
        async with httpx.AsyncClient(timeout=15.0) as h:
            r = await h.post("https://api.razorpay.com/v1/subscriptions",
                auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
                json={"plan_id": plan_id, "total_count": 12, "quantity": 1,
                      "notify_info": {"notify_phone": None, "notify_email": email}})
            return r.json()
    except Exception as e:
        logger.error(f"Razorpay error: {e}"); return None

# ══════════════════════════════════════════════════════════════════════════════
# NICHE INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

NICHE_CONTEXT = {
    "tech":          "Curiosity gaps, tech specs as hooks, comparison angles. Indian audience loves value-for-money framing.",
    "finance":       "Money amounts, percentage gains/losses, urgency. SIP, mutual funds, stock market, salary references.",
    "gaming":        "Challenge framing, game names, rank/level references. Free Fire, BGMI, GTA.",
    "fitness":       "Transformation angles, time-based promises. Desi diet, home workout, no gym.",
    "food":          "Sensory words, regional cuisine names. Street food, regional recipes, restaurant reviews.",
    "travel":        "Discovery angles, budget travel, hidden gems. Hill stations, beaches, visa-free.",
    "education":     "Skill gaps, career outcomes, time-to-learn. Job market, salary hikes, certifications.",
    "motivation":    "Struggle-to-success arcs, Indian success stories. Entrepreneur mindset.",
    "beauty":        "Transformation, product comparisons. Affordable dupes, skin tone inclusive.",
    "entertainment": "Controversy, reactions, predictions. Bollywood, OTT reviews, celebrity drama.",
    "business":      "Success stories, income figures. Indian startup ecosystem references.",
    "productivity":  "Time-saving angles, before/after routines. Indian work culture context.",
    "cricket":       "Match energy, player names, stats. IPL, World Cup references.",
    "automobiles":   "Speed, comparison, value-for-money. Maruti vs Hyundai type comparisons.",
    "examprep":      "UPSC/JEE/NEET context, rank mentions, study hacks. AIR 1 type references.",
    "health":        "Transformation, doctor-backed claims. Ayurveda and modern medicine mix.",
    "pets":          "Cute and emotional. Dog/cat focus. Breed recommendations for Indian climate.",
    "music":         "Genre-specific energy, artist names. Indian indie and Bollywood music context.",
    "realestate":    "Price reveals, location names, investment angle. Mumbai, Delhi, Bangalore.",
    "spirituality":  "Calm but impactful. Meditation, yoga, Indian philosophy.",
    "stocks":        "Market movements, portfolio gains. Sensex, Nifty, smallcap references.",
    "cooking":       "Quick recipes, ingredient reveals. Desi twists on global dishes.",
    "fashion":       "Trend reveals, outfit ideas. Indian wedding fashion, street style.",
    "parenting":     "Child development, parenting hacks. Indian family values context.",
}

def get_generate_prompt(topic, niche):
    tip = NICHE_CONTEXT.get(niche, NICHE_CONTEXT["tech"])
    return f"""You are a world-class YouTube growth strategist for the Indian creator market.

Video Topic: "{topic}"
Niche: {niche}
Niche Strategy: {tip}

Generate a complete viral content package. Respond ONLY in valid JSON.

{{
  "titles": ["title1","title2","title3","title4","title5"],
  "thumbnail": {{
    "background": "describe background scene",
    "face_expression": "exact expression",
    "text_overlay": "3-5 WORD BOLD TEXT",
    "emotion_trigger": "primary emotion",
    "ctr_score": 8.5,
    "why_it_works": "psychological hook explanation"
  }},
  "hook_script": "First 15 seconds script starting with pattern interrupt.",
  "niche_tip": "One tactical tip for this niche in YouTube India 2025.",
  "tags": {{
    "primary": ["t1","t2","t3","t4","t5"],
    "secondary": ["t6","t7","t8","t9","t10"],
    "longtail": ["phrase1","phrase2","phrase3","phrase4","phrase5"],
    "hindi_mix": ["h1","h2","h3","h4","h5"]
  }}
}}
Rules: Titles 60-70 chars max. Text overlay 3-5 words. Return ONLY JSON."""

# Generation cache
async def get_generation_cache(topic, niche):
    key = f"gen:{hashlib.md5(f'{topic.lower().strip()}{niche}'.encode()).hexdigest()}"
    cached = await redis_get(key)
    if cached:
        try: return json.loads(cached)
        except: return None
    return None

async def set_generation_cache(topic, niche, result):
    key = f"gen:{hashlib.md5(f'{topic.lower().strip()}{niche}'.encode()).hexdigest()}"
    await redis_set(key, json.dumps(result), ex=3600)

_trending_lock = asyncio.Lock()
TRENDING_TTL   = 6 * 3600

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health():
    return {"status": "ok", "service": "thumbgenius", "version": "4.0"}

# ─── User Status ──────────────────────────────────────────────────────────────
@app.get("/user/status")
async def user_status(request: Request):
    email = request.headers.get("X-User-Email", "").strip().lower()
    if not email:
        return JSONResponse({"plan": "free", "generations_used": 0, "images_used": 0})
    plan_data = await get_user_plan(email)
    limits = PLAN_LIMITS.get(plan_data.get("plan", "free"), PLAN_LIMITS["free"])
    return JSONResponse({**plan_data, **{f"{k}_limit": v for k, v in limits.items()}})

# ─── Subscribe ────────────────────────────────────────────────────────────────
@app.post("/subscribe")
async def subscribe(request: Request):
    try: data = await request.json()
    except: return JSONResponse({"error": "Invalid request"}, status_code=400)
    email = str(data.get("email", "")).strip().lower()
    plan  = str(data.get("plan",  "")).strip().lower()
    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    if plan not in ["creator", "pro"]:
        return JSONResponse({"error": "Invalid plan"}, status_code=400)
    sub = await create_razorpay_subscription(plan, email)
    if not sub or "id" not in sub:
        return JSONResponse({"error": "Payment setup failed."}, status_code=500)
    token = secrets.token_urlsafe(32)
    await sb_upsert_user(email, {"plan": plan, "razorpay_subscription_id": sub["id"],
                                  "activation_token": token, "is_active": False})
    return JSONResponse({"subscription_id": sub["id"], "razorpay_key": RAZORPAY_KEY_ID,
                         "plan": plan, "email": email,
                         "amount": 74900 if plan == "creator" else 144900})

# ─── Activate ─────────────────────────────────────────────────────────────────
@app.get("/activate", response_class=HTMLResponse)
async def activate(request: Request, token: str = ""):
    if not token: return HTMLResponse("<h1>Invalid link</h1>", status_code=400)
    user = await sb_get_user_by_token(token)
    if not user: return HTMLResponse("<h1>Link expired or invalid</h1>", status_code=400)
    await sb_update_user(user["email"], {"is_active": True, "activation_token": None,
                                          "generations_used": 0, "images_used": 0})
    await invalidate_plan_cache(user["email"])
    plan_name = "Creator" if user["plan"] == "creator" else "Pro"
    return HTMLResponse(f"""<!DOCTYPE html><html><head><title>Activated!</title>
    <style>body{{font-family:Arial;background:#02020A;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
    .box{{text-align:center;padding:40px}}h1{{color:#FDE036}}a{{background:#FDE036;color:#02020A;font-weight:bold;padding:16px 40px;border-radius:8px;text-decoration:none;display:inline-block;margin-top:24px}}</style>
    </head><body><div class="box"><h1>🎉 Activated!</h1><p>Welcome to <strong>{plan_name}</strong> Plan!</p>
    <p>{user["email"]}</p><a href="/">Start Creating →</a></div>
    <script>localStorage.setItem('tg_email','{user["email"]}');localStorage.setItem('tg_plan','{user["plan"]}');</script>
    </body></html>""")

# ─── Razorpay Webhook ─────────────────────────────────────────────────────────
@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    try:
        body = await request.body()
        sig  = request.headers.get("X-Razorpay-Signature", "")
        expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            logger.warning("Webhook signature mismatch"); return JSONResponse({"status": "ok"})
        event      = json.loads(body)
        event_type = event.get("event", "")
        logger.info(f"Razorpay webhook: {event_type}")
        if event_type in ["subscription.activated", "subscription.charged"]:
            sub = event.get("payload", {}).get("subscription", {}).get("entity", {})
            sub_id = sub.get("id")
            if sub_id:
                user = await sb_get_user_by_subscription(sub_id)
                if user:
                    await sb_update_user(user["email"], {"is_active": True, "generations_used": 0, "images_used": 0})
                    await invalidate_plan_cache(user["email"])
                    if event_type == "subscription.activated":
                        token = secrets.token_urlsafe(32)
                        await sb_update_user(user["email"], {"activation_token": token})
                        asyncio.create_task(send_magic_link(user["email"], token, user["plan"]))
        elif event_type == "subscription.cancelled":
            sub = event.get("payload", {}).get("subscription", {}).get("entity", {})
            sub_id = sub.get("id")
            if sub_id:
                user = await sb_get_user_by_subscription(sub_id)
                if user:
                    await sb_update_user(user["email"], {"plan": "free", "is_active": False})
                    await invalidate_plan_cache(user["email"])
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return JSONResponse({"status": "ok"})

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 7 — PACKAGING ASSISTANT (generate + generate-image)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/generate")
async def generate(request: Request):
    email      = request.headers.get("X-User-Email", "").strip().lower()
    admin_code = request.headers.get("X-Admin-Code", "").strip().upper()
    is_adm     = is_admin(admin_code)
    used = 0; limit = 3
    if not is_adm:
        if email:
            pd = await get_user_plan(email)
            plan = pd.get("plan","free"); used = pd.get("generations_used",0)
            limit = PLAN_LIMITS.get(plan,PLAN_LIMITS["free"])["generations"]
            if used >= limit: return JSONResponse({"error":"limit_reached","plan":plan},status_code=403)
        else:
            if await check_free_limit(request) >= 3:
                return JSONResponse({"error":"free_limit_reached"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    topic = str(data.get("topic","")).strip()
    niche = str(data.get("niche","tech")).strip()
    if not topic: return JSONResponse({"error":"Please enter a video topic"},status_code=400)
    if len(topic) > 300: return JSONResponse({"error":"Topic too long"},status_code=400)
    cached = await get_generation_cache(topic, niche)
    if cached:
        if not is_adm:
            if email: asyncio.create_task(sb_update_user(email,{"generations_used":used+1})); asyncio.create_task(invalidate_plan_cache(email))
            else: asyncio.create_task(increment_free_limit(request))
        cached["from_cache"] = True; return JSONResponse(cached)
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":"YouTube growth expert. Valid JSON only."},
                      {"role":"user","content":get_generate_prompt(topic,niche)}],
            temperature=0.8, max_tokens=1200)
        result = parse_json_safe(response.choices[0].message.content)
        if is_adm: result["uses_remaining"] = 9999
        elif email:
            asyncio.create_task(sb_update_user(email,{"generations_used":used+1})); asyncio.create_task(invalidate_plan_cache(email))
            result["uses_remaining"] = max(0, limit-used-1)
        else:
            asyncio.create_task(increment_free_limit(request))
            result["uses_remaining"] = max(0, 3-(await check_free_limit(request)+1))
        asyncio.create_task(set_generation_cache(topic,niche,result))
        return JSONResponse(result)
    except json.JSONDecodeError:
        return JSONResponse({"error":"AI returned invalid response. Try again."},status_code=500)
    except Exception as e:
        logger.error(f"/generate error: {e}"); return JSONResponse({"error":"Generation failed."},status_code=500)

@app.post("/generate-image")
async def generate_image(request: Request):
    email      = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm     = is_admin(admin_code)
    used = 0; limit = 1
    if not is_adm:
        if email:
            pd = await get_user_plan(email)
            plan = pd.get("plan","free"); used = pd.get("images_used",0)
            limit = PLAN_LIMITS.get(plan,PLAN_LIMITS["free"])["images"]
            if used >= limit: return JSONResponse({"error":"image_limit_reached","plan":plan},status_code=403)
        else:
            img_key = f"img:{hashlib.md5(get_ip(request).encode()).hexdigest()[:16]}"
            cnt = await redis_get(img_key)
            if cnt and int(cnt) >= 1: return JSONResponse({"error":"image_limit_reached"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    concept = str(data.get("concept","")).strip()
    overlay = str(data.get("text_overlay","")).strip()
    if not concept: return JSONResponse({"error":"No concept provided"},status_code=400)
    try:
        # Spell out text character by character for DALL-E accuracy
        overlay_spelled = " ".join(list(overlay.upper())) if overlay else ""
        img_prompt = (
            f"Professional YouTube thumbnail image, 16:9 widescreen format. "
            f"Scene: {concept}. "
            f"Ultra high contrast vibrant colors, cinematic lighting, photorealistic. "
            f"No watermarks, no borders. "
        )
        if overlay:
            img_prompt += (
                f"Overlay the following text EXACTLY as written in large bold white Impact font "
                f"with black stroke outline, centered prominently: '{overlay}'. "
                f"The text must be spelled correctly letter by letter: {overlay_spelled}. "
                f"Double-check spelling before rendering."
            )
        response = await client.images.generate(
            model="dall-e-3",
            prompt=img_prompt,
            size="1792x1024", quality="hd", n=1)
        if not is_adm:
            if email: asyncio.create_task(sb_update_user(email,{"images_used":used+1})); asyncio.create_task(invalidate_plan_cache(email))
            else:
                img_key = f"img:{hashlib.md5(get_ip(request).encode()).hexdigest()[:16]}"
                cnt = await redis_incr(img_key)
                if cnt == 1: await redis_expire(img_key, 30*24*3600)
        return JSONResponse({"image_url":response.data[0].url,
                             "images_remaining":9999 if is_adm else max(0,limit-used-1)})
    except Exception as e:
        logger.error(f"/generate-image error: {e}"); return JSONResponse({"error":"Image generation failed."},status_code=500)

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 1 — THUMBNAIL INTELLIGENCE ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/analyze-thumbnail")
async def analyze_thumbnail(request: Request):
    email      = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm     = is_admin(admin_code)
    if not is_adm:
        if email:
            pd = await get_user_plan(email)
            plan = pd.get("plan","free"); used = pd.get("thumb_analysis_used",0)
            limit = PLAN_LIMITS.get(plan,PLAN_LIMITS["free"])["thumb_analysis"]
            if used >= limit: return JSONResponse({"error":"analysis_limit_reached","plan":plan},status_code=403)
        else:
            if await check_free_limit(request,"tana") >= 1:
                return JSONResponse({"error":"free_limit_reached"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    image_b64 = data.get("image_b64","").strip()
    niche     = str(data.get("niche","tech")).strip()
    title     = str(data.get("title","")).strip()
    if not image_b64:
        return JSONResponse({"error":"No image provided"},status_code=400)
    # Validate base64
    try:
        if "," in image_b64: image_b64 = image_b64.split(",",1)[1]
        base64.b64decode(image_b64)
    except Exception:
        return JSONResponse({"error":"Invalid image data"},status_code=400)
    prompt = f"""You are an expert YouTube thumbnail analyst. Analyze this thumbnail for a {niche} YouTube channel.
{f'Video title: "{title}"' if title else ''}

Score this thumbnail on EXACTLY these 6 dimensions (0-10 each):
1. emotional_impact — Does it trigger a strong emotion immediately?
2. text_clarity — Is text readable, bold, and impactful?
3. face_power — Is the face expression strong and engaging? (5 if no face)
4. color_contrast — Are colors vibrant, high-contrast, eye-catching?
5. curiosity_gap — Does it make viewer desperate to click?
6. niche_fit — Does it match what top {niche} channels use?

Return ONLY this JSON:
{{
  "ctr_score": 7.5,
  "scores": {{
    "emotional_impact": 8,
    "text_clarity": 7,
    "face_power": 6,
    "color_contrast": 9,
    "curiosity_gap": 7,
    "niche_fit": 8
  }},
  "strengths": ["strength1","strength2","strength3"],
  "weaknesses": ["weakness1","weakness2","weakness3"],
  "fixes": [
    {{"dimension":"text_clarity","fix":"Exact actionable fix instruction"}},
    {{"dimension":"color_contrast","fix":"Exact actionable fix instruction"}}
  ],
  "competitor_benchmark": "How this compares to top 10% in {niche} niche in one sentence.",
  "verdict": "One punchy sentence — overall assessment of this thumbnail's CTR potential."
}}"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image_b64}","detail":"high"}},
                {"type":"text","text":prompt}
            ]}],
            max_tokens=1000)
        result = parse_json_safe(response.choices[0].message.content)
        if not is_adm and email:
            asyncio.create_task(sb_update_user(email,{"thumb_analysis_used":used+1}))
            asyncio.create_task(invalidate_plan_cache(email))
        elif not is_adm and not email:
            asyncio.create_task(increment_free_limit(request,"tana"))
        return JSONResponse(result)
    except json.JSONDecodeError:
        return JSONResponse({"error":"Analysis failed. Try again."},status_code=500)
    except Exception as e:
        logger.error(f"/analyze-thumbnail error: {e}"); return JSONResponse({"error":"Analysis failed."},status_code=500)

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 2 — CTR PREDICTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/predict-ctr")
async def predict_ctr(request: Request):
    email      = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm     = is_admin(admin_code)
    if not is_adm:
        if email:
            pd = await get_user_plan(email)
            plan = pd.get("plan","free"); used = pd.get("ctr_predict_used",0)
            limit = PLAN_LIMITS.get(plan,PLAN_LIMITS["free"])["ctr_predict"]
            if limit == 0: return JSONResponse({"error":"upgrade_required","plan":plan},status_code=403)
            if used >= limit: return JSONResponse({"error":"ctr_limit_reached","plan":plan},status_code=403)
        else:
            return JSONResponse({"error":"login_required"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    image_b64 = data.get("image_b64","").strip()
    titles    = data.get("titles",[])
    niche     = str(data.get("niche","tech")).strip()
    if not image_b64 or not titles:
        return JSONResponse({"error":"Image and at least one title required"},status_code=400)
    if "," in image_b64: image_b64 = image_b64.split(",",1)[1]
    titles_str = "\n".join([f"{i+1}. {t}" for i,t in enumerate(titles[:5])])
    prompt = f"""You are a YouTube CTR prediction expert specializing in the Indian market.
Analyze this thumbnail paired with each title candidate for a {niche} channel.

Title candidates:
{titles_str}

For each title, predict the CTR performance of the thumbnail+title combination.
Return ONLY this JSON:
{{
  "predictions": [
    {{
      "title": "exact title text",
      "ctr_range": "4.2%-6.8%",
      "synergy_score": 78,
      "scroll_stop_probability": 65,
      "emotional_angle": "Curiosity Gap",
      "reasoning": "One sentence explanation of why this combination works or doesn't",
      "rank": 1
    }}
  ],
  "winner_index": 0,
  "winner_reasoning": "Two sentences explaining why the winning combination is strongest.",
  "thumbnail_assessment": "One sentence on the thumbnail's standalone CTR potential.",
  "improvement_tip": "One specific change that would boost CTR across all combinations."
}}
Rank predictions from best (rank 1) to worst. Include all {len(titles)} titles."""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image_b64}","detail":"high"}},
                {"type":"text","text":prompt}
            ]}],
            max_tokens=1200)
        result = parse_json_safe(response.choices[0].message.content)
        if not is_adm and email:
            asyncio.create_task(sb_update_user(email,{"ctr_predict_used":used+1}))
            asyncio.create_task(invalidate_plan_cache(email))
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"/predict-ctr error: {e}"); return JSONResponse({"error":"Prediction failed."},status_code=500)

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 3 — VIRAL REVERSE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/reverse-engineer")
async def reverse_engineer(request: Request):
    email      = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm     = is_admin(admin_code)
    if not is_adm:
        if email:
            pd = await get_user_plan(email)
            plan = pd.get("plan","free"); used = pd.get("reverse_used",0)
            limit = PLAN_LIMITS.get(plan,PLAN_LIMITS["free"])["reverse"]
            if used >= limit: return JSONResponse({"error":"reverse_limit_reached","plan":plan},status_code=403)
        else:
            if await check_free_limit(request,"rev") >= 2:
                return JSONResponse({"error":"free_limit_reached"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    image_b64   = data.get("image_b64","").strip()
    creator_niche = str(data.get("niche","tech")).strip()
    if not image_b64:
        return JSONResponse({"error":"No image provided"},status_code=400)
    if "," in image_b64: image_b64 = image_b64.split(",",1)[1]
    prompt = f"""You are a viral YouTube thumbnail strategist. Reverse engineer this thumbnail completely.
The creator asking wants to replicate its success for their {creator_niche} channel.

Perform a 9-layer deconstruction. Return ONLY this JSON:
{{
  "layers": {{
    "composition": "Describe the visual layout — where elements are positioned and why",
    "color_psychology": "What the colors communicate psychologically and emotionally",
    "typography": "Font style, size hierarchy, text placement strategy",
    "face_expression": "What emotion the face conveys and its psychological effect (or note if no face)",
    "emotion_trigger": "The primary emotion triggered in the viewer on first glance",
    "curiosity_mechanism": "Exactly how it creates a curiosity gap or information gap",
    "text_visual_synergy": "How the text and visuals reinforce each other",
    "scroll_stop_factor": "What specifically makes a viewer stop scrolling at this thumbnail",
    "social_proof_signals": "Any authority, credibility, or social proof signals present"
  }},
  "technique_tags": ["Curiosity Gap","Shock Factor","Social Proof","FOMO","Authority","Before-After","Pattern Interrupt"],
  "ctr_tier": "High (7%+)",
  "top_3_elements": ["Most impactful element","Second most","Third most"],
  "replication_blueprint": [
    {{"step": 1, "action": "Exact step to replicate this technique in {creator_niche}"}},
    {{"step": 2, "action": "Exact step"}},
    {{"step": 3, "action": "Exact step"}},
    {{"step": 4, "action": "Exact step"}},
    {{"step": 5, "action": "Exact step"}}
  ],
  "dos": ["What to copy directly for {creator_niche}","Second do"],
  "donts": ["What NOT to copy — why it won't work in {creator_niche}","Second dont"],
  "summary": "Two sentences: what makes this thumbnail powerful and how to adapt it."
}}"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image_b64}","detail":"high"}},
                {"type":"text","text":prompt}
            ]}],
            max_tokens=1500)
        result = parse_json_safe(response.choices[0].message.content)
        if not is_adm and email:
            asyncio.create_task(sb_update_user(email,{"reverse_used":used+1}))
            asyncio.create_task(invalidate_plan_cache(email))
        elif not is_adm and not email:
            asyncio.create_task(increment_free_limit(request,"rev"))
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"/reverse-engineer error: {e}"); return JSONResponse({"error":"Reverse engineering failed."},status_code=500)

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 4 — A/B TESTING SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/ab-test")
async def ab_test(request: Request):
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    title_a = str(data.get("titleA","")).strip()
    title_b = str(data.get("titleB","")).strip()
    if not title_a or not title_b:
        return JSONResponse({"error":"Please enter both titles"},status_code=400)
    try:
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":"YouTube CTR expert. JSON only."},
                {"role":"user","content":f'Compare these YouTube titles for Indian audience. JSON only.\nTitle A: "{title_a}"\nTitle B: "{title_b}"\nReturn: {{"winner":"A or B","score_a":8,"score_b":7,"reasoning":"2-3 sentences","emotional_angle_a":"Curiosity Gap","emotional_angle_b":"Shock Factor","improvement_a":"one specific fix for title A","improvement_b":"one specific fix for title B"}}'}
            ],
            temperature=0.7, max_tokens=400)
        return JSONResponse(parse_json_safe(response.choices[0].message.content))
    except Exception as e:
        logger.error(f"/ab-test error: {e}"); return JSONResponse({"error":"Test failed."},status_code=500)

@app.post("/ab-test-thumbnails")
async def ab_test_thumbnails(request: Request):
    email      = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm     = is_admin(admin_code)
    if not is_adm:
        if email:
            pd = await get_user_plan(email)
            plan = pd.get("plan","free"); used = pd.get("ab_tests_used",0)
            limit = PLAN_LIMITS.get(plan,PLAN_LIMITS["free"])["ab_tests"]
            if used >= limit: return JSONResponse({"error":"ab_limit_reached","plan":plan},status_code=403)
        else:
            if await check_free_limit(request,"abt") >= 3:
                return JSONResponse({"error":"free_limit_reached"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    img_a   = data.get("image_a_b64","").strip()
    img_b   = data.get("image_b_b64","").strip()
    title_a = str(data.get("title_a","")).strip()
    title_b = str(data.get("title_b","")).strip()
    niche   = str(data.get("niche","tech")).strip()
    if not img_a or not img_b:
        return JSONResponse({"error":"Both thumbnail images required"},status_code=400)
    if "," in img_a: img_a = img_a.split(",",1)[1]
    if "," in img_b: img_b = img_b.split(",",1)[1]
    prompt = f"""You are a YouTube A/B testing expert for the Indian market.
Compare these two thumbnails for a {niche} channel.
{f'Thumbnail A title: "{title_a}"' if title_a else ''}
{f'Thumbnail B title: "{title_b}"' if title_b else ''}

Simulate how Indian YouTube viewers would respond to each thumbnail.
Return ONLY this JSON:
{{
  "winner": "A",
  "win_probability": 68,
  "confidence": "High",
  "ctr_advantage": "+1.4%",
  "scores": {{
    "a": {{"overall":7.2,"emotional_impact":8,"text_clarity":7,"visual_appeal":7,"curiosity":7}},
    "b": {{"overall":5.8,"emotional_impact":6,"text_clarity":5,"visual_appeal":6,"curiosity":6}}
  }},
  "winner_strengths": ["Strength 1 of winner","Strength 2","Strength 3"],
  "loser_weaknesses": ["Weakness 1 of loser","Weakness 2"],
  "element_differences": [
    {{"element":"Background","a_assessment":"description","b_assessment":"description","winner":"A"}},
    {{"element":"Text Overlay","a_assessment":"description","b_assessment":"description","winner":"B"}},
    {{"element":"Color Scheme","a_assessment":"description","b_assessment":"description","winner":"A"}}
  ],
  "v3_suggestion": "One paragraph describing how to combine the best elements of both into a superior Version 3.",
  "audience_segment_notes": "How different Indian audience segments (mobile-first, age 18-24 vs 25-35) might respond differently."
}}"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":[
                {"type":"text","text":"Thumbnail A:"},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_a}","detail":"high"}},
                {"type":"text","text":"Thumbnail B:"},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b}","detail":"high"}},
                {"type":"text","text":prompt}
            ]}],
            max_tokens=1200)
        result = parse_json_safe(response.choices[0].message.content)
        if not is_adm and email:
            asyncio.create_task(sb_update_user(email,{"ab_tests_used":used+1}))
            asyncio.create_task(invalidate_plan_cache(email))
        elif not is_adm and not email:
            asyncio.create_task(increment_free_limit(request,"abt"))
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"/ab-test-thumbnails error: {e}"); return JSONResponse({"error":"Test failed."},status_code=500)

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 5 — INSPIRATION LIBRARY
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/inspiration/library")
async def inspiration_library(request: Request, niche: str = "", trigger: str = ""):
    cache_key = f"library:{niche}:{trigger}"
    cached = await redis_get(cache_key)
    if cached:
        try: return JSONResponse(json.loads(cached))
        except: pass
    niche_filter   = f"Focus on {niche} niche thumbnails." if niche else "Mix across all niches."
    trigger_filter = f"Show thumbnails that use the {trigger} psychological technique." if trigger else "Mix all psychological techniques."
    prompt = f"""Generate 12 high-performing YouTube thumbnail concepts for the Inspiration Library.
{niche_filter} {trigger_filter} Focus on Indian YouTube market (2024-2025).

Return ONLY a JSON array:
[{{
  "id": "unique_id",
  "title": "Example video title this thumbnail was for",
  "niche": "tech",
  "technique_tags": ["Curiosity Gap","Shock Factor"],
  "ctr_tier": "High (7%+)",
  "background_description": "Detailed visual description of the thumbnail background",
  "text_overlay": "TEXT ON THUMBNAIL",
  "face_expression": "shocked with mouth open" or "none",
  "color_palette": ["#FF0000","#FFFFFF","#000000"],
  "why_it_works": "One sentence psychological explanation",
  "heat_score": 9.2
}}]

Include variety: mix niches, techniques, and CTR tiers. Make descriptions specific enough to visualize."""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":"YouTube thumbnail expert. JSON only."},
                      {"role":"user","content":prompt}],
            temperature=0.9, max_tokens=2000)
        result = parse_json_safe(response.choices[0].message.content)
        await redis_set(cache_key, json.dumps(result), ex=3600)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"/inspiration/library error: {e}"); return JSONResponse({"error":"Failed to load library."},status_code=500)

@app.post("/inspiration/save")
async def inspiration_save(request: Request):
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email: return JSONResponse({"error":"Login required"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    await sb_save_inspiration(email, {
        "item_id": data.get("id",""),
        "title": data.get("title",""),
        "niche": data.get("niche",""),
        "technique_tags": json.dumps(data.get("technique_tags",[])),
        "why_it_works": data.get("why_it_works",""),
        "notes": data.get("notes",""),
    })
    return JSONResponse({"status":"saved"})

@app.get("/inspiration/saved")
async def inspiration_saved(request: Request):
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email: return JSONResponse([])
    items = await sb_get_inspirations(email)
    return JSONResponse(items)

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 6 — CREATOR BRANDING SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/branding/extract")
async def branding_extract(request: Request):
    email = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm = is_admin(admin_code)
    if not is_adm and not email:
        return JSONResponse({"error":"Login required"},status_code=403)
    if not is_adm and email:
        pd = await get_user_plan(email)
        if pd.get("plan","free") == "free":
            return JSONResponse({"error":"upgrade_required","plan":"free"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    images_b64 = data.get("images_b64",[])
    niche      = str(data.get("niche","tech")).strip()
    if not images_b64 or len(images_b64) < 1:
        return JSONResponse({"error":"At least 1 thumbnail required"},status_code=400)
    # Process up to 5 images
    images_b64 = images_b64[:5]
    processed  = []
    for img in images_b64:
        if "," in img: img = img.split(",",1)[1]
        processed.append(img)
    content_parts = [{"type":"text","text":f"Analyze these {len(processed)} YouTube thumbnails from the same {niche} creator. Extract their visual brand identity."}]
    for i, img in enumerate(processed):
        content_parts.append({"type":"text","text":f"Thumbnail {i+1}:"})
        content_parts.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img}","detail":"high"}})
    content_parts.append({"type":"text","text":f"""Extract the visual brand DNA from these thumbnails. Return ONLY this JSON:
{{
  "color_palette": {{
    "primary": "#FF0000",
    "secondary": "#FFFFFF",
    "background": "#000000",
    "accent": "#FDE036",
    "text": "#FFFFFF"
  }},
  "typography_style": "Bold Impact-style fonts, all caps, large size",
  "font_recommendation": "Impact",
  "expression_style": "High energy, shocked/excited expressions",
  "composition_pattern": "Face on right, text on left, high contrast background",
  "recurring_elements": ["Red arrows","Circular face cutout","Bold yellow text"],
  "brand_mood": "High energy, urgent, clickbait-adjacent but credible",
  "consistency_score": 72,
  "inconsistencies": ["Color palette changes across thumbnails","Font style varies"],
  "brand_audit": "Two sentences describing the current brand strength and main weakness.",
  "improvement_recommendations": [
    "Specific recommendation 1 to strengthen brand consistency",
    "Specific recommendation 2",
    "Specific recommendation 3"
  ]
}}"""})
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":content_parts}],
            max_tokens=1000)
        return JSONResponse(parse_json_safe(response.choices[0].message.content))
    except Exception as e:
        logger.error(f"/branding/extract error: {e}"); return JSONResponse({"error":"Brand extraction failed."},status_code=500)

@app.post("/branding/save")
async def branding_save(request: Request):
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email: return JSONResponse({"error":"Login required"},status_code=403)
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    await sb_save_brand_kit(email, data)
    await redis_set(f"brandkit:{email}", json.dumps(data), ex=86400)
    return JSONResponse({"status":"saved"})

@app.get("/branding/get")
async def branding_get(request: Request):
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email: return JSONResponse({"kit":None})
    cached = await redis_get(f"brandkit:{email}")
    if cached:
        try: return JSONResponse({"kit":json.loads(cached)})
        except: pass
    kit = await sb_get_brand_kit(email)
    if kit:
        kit_data = json.loads(kit.get("kit_data","{}"))
        await redis_set(f"brandkit:{email}", json.dumps(kit_data), ex=86400)
        return JSONResponse({"kit":kit_data})
    return JSONResponse({"kit":None})

# ══════════════════════════════════════════════════════════════════════════════
# EXISTING ROUTES — Channel Analyzer, Trending
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/analyze-channel")
async def analyze_channel(request: Request):
    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    titles = str(data.get("titles","")).strip()
    if not titles: return JSONResponse({"error":"Please enter your video titles"},status_code=400)
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":"YouTube growth expert. JSON only."},
                {"role":"user","content":f'Analyze these Indian YouTube video titles. JSON only.\nTitles: "{titles}"\nReturn: {{"ctr_score":7,"emotion_score":6,"clarity_score":8,"issues":[{{"title":"issue","detail":"explanation"}}],"fixes":[{{"title":"fix","detail":"how to apply"}}],"rewrites":[{{"original":"old","improved":"better"}}]}}'}
            ],
            temperature=0.7, max_tokens=800)
        return JSONResponse(parse_json_safe(response.choices[0].message.content))
    except Exception as e:
        logger.error(f"/analyze-channel error: {e}"); return JSONResponse({"error":"Analysis failed."},status_code=500)

@app.get("/trending")
async def trending(request: Request, niches: str = ""):
    # Parse requested niches
    VALID_NICHES = {"tech","finance","gaming","fitness","food","travel","education","motivation",
                    "beauty","entertainment","business","productivity","cricket","automobiles",
                    "examprep","health","music","realestate","spirituality","stocks"}
    if niches:
        requested = [n.strip().lower() for n in niches.split(",") if n.strip().lower() in VALID_NICHES]
    else:
        requested = ["tech","finance","gaming","fitness","cricket","automobiles","examprep","motivation"]
    if not requested:
        requested = ["tech","finance"]

    # Cache key per niche combo
    cache_key = "trending:" + "_".join(sorted(requested))
    cached = await redis_get(cache_key)
    if cached:
        try:
            parsed = json.loads(cached)
            if isinstance(parsed, list) and len(parsed) > 0:
                return JSONResponse(parsed)
        except: pass

    async with _trending_lock:
        cached = await redis_get(cache_key)
        if cached:
            try:
                parsed = json.loads(cached)
                if isinstance(parsed, list) and len(parsed) > 0:
                    return JSONResponse(parsed)
            except: pass
        try:
            per_niche = max(3, min(5, 20 // len(requested)))
            niche_list = ", ".join(requested)
            total = per_niche * len(requested)
            prompt = f"""Generate {total} trending YouTube video topics for Indian creators right now in 2025.
Niches requested: {niche_list}
Generate exactly {per_niche} topics per niche.

Return a JSON object with a "topics" key containing an array:
{{"topics": [
  {{"niche":"tech","topic":"Specific compelling video title","why":"One sentence why this is trending in India right now","heat":"🔥🔥 High Momentum"}},
  ...
]}}

Rules:
- Topics must be specific, actionable video title ideas (not generic)
- Highly relevant to Indian YouTube audience in 2025
- Each topic must have all 4 fields: niche, topic, why, heat
- niche must exactly match one of: {niche_list}"""

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system","content":"YouTube trends expert for Indian creators. Return only valid JSON."},
                    {"role":"user","content":prompt}
                ],
                temperature=0.85, max_tokens=2000,
                response_format={"type": "json_object"})

            raw = response.choices[0].message.content.strip()
            logger.info(f"/trending raw: {raw[:300]}")
            parsed = json.loads(raw)

            # Extract array from wrapper
            if isinstance(parsed, dict):
                result = next((v for v in parsed.values() if isinstance(v, list)), None)
                if not result:
                    raise ValueError(f"No array in response keys: {list(parsed.keys())}")
            elif isinstance(parsed, list):
                result = parsed
            else:
                raise ValueError(f"Unexpected type: {type(parsed)}")

            if len(result) == 0:
                raise ValueError("Empty topics returned")

            # Filter to only requested niches
            result = [t for t in result if isinstance(t, dict) and t.get("niche","") in requested]

            await redis_set(cache_key, json.dumps(result), ex=TRENDING_TTL)
            return JSONResponse(result)

        except Exception as e:
            logger.error(f"/trending error: {e}")
            return JSONResponse({"error": f"Failed to load trending topics: {str(e)}"}, status_code=500)
