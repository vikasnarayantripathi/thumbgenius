"""
ThumbGenius — main.py v3.1
Full production system: Supabase + Redis + Razorpay + Resend + CSP
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
import os, json, asyncio, logging, hashlib, hmac, secrets
import httpx

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
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

MAX_FREE        = 3
MAX_FREE_IMAGES = 1
PLAN_LIMITS = {
    "free":    {"generations": 3,   "images": 1},
    "creator": {"generations": 100, "images": 20},
    "pro":     {"generations": 300, "images": 50},
}

# ─── Admin codes ──────────────────────────────────────────────────────────────
ADMIN_CODES = {
    "VIKAS2025": {"plans": ["creator", "pro"], "label": "Admin Access"},
}

def is_valid_admin_code(code: str) -> bool:
    return code.upper() in ADMIN_CODES

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ThumbGenius v3.1 starting up...")
    yield
    logger.info("ThumbGenius shutting down...")

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)

# ─── CSP Middleware ───────────────────────────────────────────────────────────
class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://checkout.razorpay.com "
                "https://fonts.googleapis.com "
                "https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' "
                "https://fonts.googleapis.com; "
            "font-src 'self' "
                "https://fonts.gstatic.com; "
            "img-src 'self' data: blob: "
                "https://oaidalleapiprodscus.blob.core.windows.net "
                "https://*.openai.com "
                "https://*.blob.core.windows.net; "
            "connect-src 'self' "
                "https://api.openai.com "
                "https://api.razorpay.com "
                "https://lumberjack.razorpay.com "
                "https://jfestnbagyjrpoczhxbw.supabase.co; "
            "frame-src https://api.razorpay.com "
                "https://checkout.razorpay.com; "
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
client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=2, timeout=30.0)

# ─── Redis (Upstash REST) ─────────────────────────────────────────────────────
async def redis_get(key: str):
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            r = await h.get(
                f"{UPSTASH_REDIS_REST_URL}/get/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
            )
            return r.json().get("result")
    except Exception as e:
        logger.warning(f"Redis GET error: {e}")
        return None

async def redis_set(key: str, value: str, ex: int = None):
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            url = f"{UPSTASH_REDIS_REST_URL}/set/{key}/{value}"
            if ex:
                url += f"/ex/{ex}"
            await h.get(url, headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
    except Exception as e:
        logger.warning(f"Redis SET error: {e}")

async def redis_incr(key: str) -> int:
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            r = await h.get(
                f"{UPSTASH_REDIS_REST_URL}/incr/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
            )
            return r.json().get("result", 1)
    except Exception as e:
        logger.warning(f"Redis INCR error: {e}")
        return 1

async def redis_expire(key: str, seconds: int):
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            await h.get(
                f"{UPSTASH_REDIS_REST_URL}/expire/{key}/{seconds}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
            )
    except Exception as e:
        logger.warning(f"Redis EXPIRE error: {e}")

# ─── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

async def sb_get_user(email: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(
                f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}&select=*",
                headers=SUPABASE_HEADERS
            )
            data = r.json()
            return data[0] if data else None
    except Exception as e:
        logger.error(f"Supabase get_user error: {e}")
        return None

async def sb_upsert_user(email: str, data: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post(
                f"{SUPABASE_URL}/rest/v1/users",
                headers={**SUPABASE_HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"},
                json={"email": email, **data}
            )
    except Exception as e:
        logger.error(f"Supabase upsert error: {e}")

async def sb_update_user(email: str, data: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.patch(
                f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}",
                headers=SUPABASE_HEADERS,
                json=data
            )
    except Exception as e:
        logger.error(f"Supabase update error: {e}")

async def sb_get_user_by_token(token: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(
                f"{SUPABASE_URL}/rest/v1/users?activation_token=eq.{token}&select=*",
                headers=SUPABASE_HEADERS
            )
            data = r.json()
            return data[0] if data else None
    except Exception as e:
        logger.error(f"Supabase get_by_token error: {e}")
        return None

async def sb_get_user_by_subscription(sub_id: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            r = await h.get(
                f"{SUPABASE_URL}/rest/v1/users?razorpay_subscription_id=eq.{sub_id}&select=*",
                headers=SUPABASE_HEADERS
            )
            data = r.json()
            return data[0] if data else None
    except Exception as e:
        logger.error(f"Supabase get_by_subscription error: {e}")
        return None

# ─── User plan helpers ────────────────────────────────────────────────────────
async def get_user_plan(email: str) -> dict:
    if not email:
        return {"plan": "free", "generations_used": 0, "images_used": 0}
    cache_key = f"plan:{email}"
    cached = await redis_get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    user = await sb_get_user(email)
    if not user:
        return {"plan": "free", "generations_used": 0, "images_used": 0}
    plan_data = {
        "plan": user.get("plan", "free"),
        "generations_used": user.get("generations_used", 0),
        "images_used": user.get("images_used", 0),
        "is_active": user.get("is_active", False),
    }
    await redis_set(cache_key, json.dumps(plan_data), ex=300)
    return plan_data

async def invalidate_plan_cache(email: str):
    await redis_set(f"plan:{email}", "", ex=1)

# ─── IP helpers ───────────────────────────────────────────────────────────────
def get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host

def get_fingerprint(request: Request) -> str:
    ip = get_ip(request)
    ua = request.headers.get("User-Agent", "")[:50]
    return hashlib.md5(f"{ip}{ua}".encode()).hexdigest()[:16]

async def check_free_limit(request: Request) -> int:
    fp = get_fingerprint(request)
    count = await redis_get(f"free:{fp}")
    return int(count) if count else 0

async def increment_free_limit(request: Request):
    fp = get_fingerprint(request)
    key = f"free:{fp}"
    count = await redis_incr(key)
    if count == 1:
        await redis_expire(key, 30 * 24 * 3600)

# ─── Resend email ─────────────────────────────────────────────────────────────
async def send_magic_link(email: str, token: str, plan: str):
    activation_url = f"{APP_URL}/activate?token={token}"
    plan_name = "Creator" if plan == "creator" else "Pro"
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={
                    "from": f"ThumbGenius <{FROM_EMAIL}>",
                    "to": [email],
                    "subject": f"🎉 Activate your ThumbGenius {plan_name} Plan",
                    "html": f"""
                    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
                                background:#02020A;color:#fff;padding:40px;border-radius:12px;">
                        <h1 style="color:#FDE036;font-size:28px;margin-bottom:8px;">ThumbGenius</h1>
                        <p style="color:#aaa;margin-bottom:32px;">YouTube Packaging Intelligence Platform</p>
                        <h2 style="color:#fff;font-size:22px;">Welcome to {plan_name} Plan! 🚀</h2>
                        <p style="color:#ccc;font-size:16px;line-height:1.6;">
                            Click below to activate your account and start engineering
                            thumbnails that convert impressions into clicks.
                        </p>
                        <a href="{activation_url}"
                           style="display:inline-block;background:#FDE036;color:#02020A;
                                  font-weight:bold;font-size:18px;padding:16px 40px;
                                  border-radius:8px;text-decoration:none;margin:24px 0;">
                            Activate My Account →
                        </a>
                        <p style="color:#666;font-size:14px;margin-top:32px;">
                            This link expires in 24 hours. If you didn't sign up, ignore this email.
                        </p>
                        <hr style="border-color:#333;margin:32px 0;">
                        <p style="color:#444;font-size:12px;">ThumbGenius · thumbgenius.in</p>
                    </div>
                    """
                }
            )
        logger.info(f"Magic link sent to {email}")
    except Exception as e:
        logger.error(f"Email send error: {e}")

# ─── Razorpay subscription ────────────────────────────────────────────────────
async def create_razorpay_subscription(plan: str, email: str) -> dict | None:
    plan_id = RAZORPAY_CREATOR_PLAN_ID if plan == "creator" else RAZORPAY_PRO_PLAN_ID
    try:
        async with httpx.AsyncClient(timeout=15.0) as h:
            r = await h.post(
                "https://api.razorpay.com/v1/subscriptions",
                auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
                json={
                    "plan_id": plan_id,
                    "total_count": 12,
                    "quantity": 1,
                    "notify_info": {"notify_phone": None, "notify_email": email}
                }
            )
            return r.json()
    except Exception as e:
        logger.error(f"Razorpay create subscription error: {e}")
        return None

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
  "hook_script": "Write the exact first 15 seconds of the video as a script. Start with a pattern interrupt.",
  "niche_tip": "One specific tactical tip for growing in this niche on YouTube India in 2025.",
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

# ─── Caches ───────────────────────────────────────────────────────────────────
async def get_generation_cache(topic: str, niche: str):
    key = f"gen:{hashlib.md5(f'{topic.lower().strip()}{niche}'.encode()).hexdigest()}"
    cached = await redis_get(key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            return None
    return None

async def set_generation_cache(topic: str, niche: str, result: dict):
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
    return {"status": "ok", "service": "thumbgenius", "version": "3.1"}

# ─── Subscribe ────────────────────────────────────────────────────────────────
@app.post("/subscribe")
async def subscribe(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    email = str(data.get("email", "")).strip().lower()
    plan  = str(data.get("plan", "")).strip().lower()

    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    if plan not in ["creator", "pro"]:
        return JSONResponse({"error": "Invalid plan"}, status_code=400)

    sub = await create_razorpay_subscription(plan, email)
    if not sub or "id" not in sub:
        logger.error(f"Razorpay subscription creation failed: {sub}")
        return JSONResponse({"error": "Payment setup failed. Please try again."}, status_code=500)

    token = secrets.token_urlsafe(32)
    await sb_upsert_user(email, {
        "plan": plan,
        "razorpay_subscription_id": sub["id"],
        "activation_token": token,
        "is_active": False,
    })

    return JSONResponse({
        "subscription_id": sub["id"],
        "razorpay_key": RAZORPAY_KEY_ID,
        "plan": plan,
        "email": email,
        "amount": 74900 if plan == "creator" else 144900,
    })

# ─── Activate ─────────────────────────────────────────────────────────────────
@app.get("/activate", response_class=HTMLResponse)
async def activate(request: Request, token: str = ""):
    if not token:
        return HTMLResponse("<h1>Invalid link</h1>", status_code=400)

    user = await sb_get_user_by_token(token)
    if not user:
        return HTMLResponse("<h1>Link expired or invalid</h1>", status_code=400)

    await sb_update_user(user["email"], {
        "is_active": True,
        "activation_token": None,
        "generations_used": 0,
        "images_used": 0,
    })
    await invalidate_plan_cache(user["email"])

    plan_name = "Creator" if user["plan"] == "creator" else "Pro"
    return HTMLResponse(f"""<!DOCTYPE html>
<html>
<head>
    <title>ThumbGenius — Activated!</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family:Arial,sans-serif; background:#02020A; color:#fff;
               display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
        .box {{ text-align:center; padding:40px; }}
        h1 {{ color:#FDE036; font-size:32px; }}
        p {{ color:#ccc; font-size:18px; }}
        a {{ display:inline-block; background:#FDE036; color:#02020A; font-weight:bold;
             padding:16px 40px; border-radius:8px; text-decoration:none; margin-top:24px; font-size:18px; }}
    </style>
</head>
<body>
    <div class="box">
        <h1>🎉 Account Activated!</h1>
        <p>Welcome to ThumbGenius <strong>{plan_name}</strong> Plan!</p>
        <p>Your email: <strong>{user["email"]}</strong></p>
        <a href="/">Start Creating →</a>
    </div>
    <script>
        localStorage.setItem('tg_email', '{user["email"]}');
        localStorage.setItem('tg_plan', '{user["plan"]}');
    </script>
</body>
</html>""")

# ─── User status ──────────────────────────────────────────────────────────────
@app.get("/user/status")
async def user_status(request: Request):
    email = request.headers.get("X-User-Email", "").strip().lower()
    if not email:
        return JSONResponse({"plan": "free", "generations_used": 0, "images_used": 0})
    plan_data = await get_user_plan(email)
    limits = PLAN_LIMITS.get(plan_data.get("plan", "free"), PLAN_LIMITS["free"])
    return JSONResponse({**plan_data, "generations_limit": limits["generations"], "images_limit": limits["images"]})

# ─── Razorpay Webhook ─────────────────────────────────────────────────────────
@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    try:
        body = await request.body()
        sig  = request.headers.get("X-Razorpay-Signature", "")
        expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            logger.warning("Razorpay webhook signature mismatch")
            return JSONResponse({"status": "ok"})

        event      = json.loads(body)
        event_type = event.get("event", "")
        logger.info(f"Razorpay webhook: {event_type}")

        if event_type in ["subscription.activated", "subscription.charged"]:
            sub    = event.get("payload", {}).get("subscription", {}).get("entity", {})
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
            sub    = event.get("payload", {}).get("subscription", {}).get("entity", {})
            sub_id = sub.get("id")
            if sub_id:
                user = await sb_get_user_by_subscription(sub_id)
                if user:
                    await sb_update_user(user["email"], {"plan": "free", "is_active": False})
                    await invalidate_plan_cache(user["email"])

    except Exception as e:
        logger.error(f"Webhook error: {e}")

    return JSONResponse({"status": "ok"})

# ─── Generate ─────────────────────────────────────────────────────────────────
@app.post("/generate")
async def generate(request: Request):
    email      = request.headers.get("X-User-Email", "").strip().lower()
    admin_code = request.headers.get("X-Admin-Code", "").strip().upper()
    is_admin   = admin_code and is_valid_admin_code(admin_code)

    used = 0; limit = MAX_FREE
    if not is_admin:
        if email:
            plan_data = await get_user_plan(email)
            plan      = plan_data.get("plan", "free")
            used      = plan_data.get("generations_used", 0)
            limit     = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["generations"]
            if used >= limit:
                return JSONResponse({"error": "limit_reached", "plan": plan}, status_code=403)
        else:
            count = await check_free_limit(request)
            if count >= MAX_FREE:
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

    cached = await get_generation_cache(topic, niche)
    if cached:
        if not is_admin:
            if email:
                asyncio.create_task(sb_update_user(email, {"generations_used": used + 1}))
                asyncio.create_task(invalidate_plan_cache(email))
            else:
                asyncio.create_task(increment_free_limit(request))
        cached["from_cache"] = True
        return JSONResponse(cached)

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

        if is_admin:
            result["uses_remaining"] = 9999
        elif email:
            asyncio.create_task(sb_update_user(email, {"generations_used": used + 1}))
            asyncio.create_task(invalidate_plan_cache(email))
            result["uses_remaining"] = max(0, limit - used - 1)
        else:
            asyncio.create_task(increment_free_limit(request))
            new_used = await check_free_limit(request) + 1
            result["uses_remaining"] = max(0, MAX_FREE - new_used)

        asyncio.create_task(set_generation_cache(topic, niche, result))
        return JSONResponse(result)

    except json.JSONDecodeError:
        logger.error("JSON decode error in /generate")
        return JSONResponse({"error": "AI returned invalid response. Please try again."}, status_code=500)
    except Exception as e:
        logger.error(f"/generate error: {e}")
        return JSONResponse({"error": "Generation failed. Please try again."}, status_code=500)

# ─── Generate Image ───────────────────────────────────────────────────────────
@app.post("/generate-image")
async def generate_image(request: Request):
    email      = request.headers.get("X-User-Email", "").strip().lower()
    admin_code = request.headers.get("X-Admin-Code", "").strip().upper()
    is_admin   = admin_code and is_valid_admin_code(admin_code)

    used = 0; limit = MAX_FREE_IMAGES
    if not is_admin:
        if email:
            plan_data = await get_user_plan(email)
            plan      = plan_data.get("plan", "free")
            used      = plan_data.get("images_used", 0)
            limit     = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["images"]
            if used >= limit:
                return JSONResponse({"error": "image_limit_reached", "plan": plan}, status_code=403)
        else:
            img_key   = f"img:{hashlib.md5(get_ip(request).encode()).hexdigest()[:16]}"
            img_count = await redis_get(img_key)
            if img_count and int(img_count) >= MAX_FREE_IMAGES:
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

        if not is_admin:
            if email:
                asyncio.create_task(sb_update_user(email, {"images_used": used + 1}))
                asyncio.create_task(invalidate_plan_cache(email))
            else:
                img_key = f"img:{hashlib.md5(get_ip(request).encode()).hexdigest()[:16]}"
                count   = await redis_incr(img_key)
                if count == 1:
                    await redis_expire(img_key, 30 * 24 * 3600)

        return JSONResponse({
            "image_url": response.data[0].url,
            "images_remaining": 9999 if is_admin else max(0, limit - used - 1),
        })
    except Exception as e:
        logger.error(f"/generate-image error: {e}")
        return JSONResponse({"error": "Image generation failed. Please try again."}, status_code=500)

# ─── A/B Test ─────────────────────────────────────────────────────────────────
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
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "YouTube CTR expert. JSON only."},
                {"role": "user", "content": (
                    "Compare these two YouTube titles for Indian audience. JSON only, no markdown.\n"
                    f'Title A: "{title_a}"\nTitle B: "{title_b}"\n'
                    'Return: {"winner":"A or B","score_a":8,"score_b":7,"reasoning":"2-3 sentences"}'
                )},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        return JSONResponse(parse_json_safe(response.choices[0].message.content))
    except Exception as e:
        logger.error(f"/ab-test error: {e}")
        return JSONResponse({"error": "Test failed. Please try again."}, status_code=500)

# ─── Analyze Channel ──────────────────────────────────────────────────────────
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
                {"role": "system", "content": "YouTube growth expert. JSON only."},
                {"role": "user", "content": (
                    "Analyze these Indian YouTube video titles. JSON only, no markdown.\n"
                    f'Titles: "{titles}"\n'
                    'Return: {"ctr_score":7,"emotion_score":6,"clarity_score":8,'
                    '"issues":[{"title":"issue","detail":"explanation"}],'
                    '"fixes":[{"title":"fix","detail":"how to apply"}],'
                    '"rewrites":[{"original":"old","improved":"better"}]}'
                )},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        return JSONResponse(parse_json_safe(response.choices[0].message.content))
    except Exception as e:
        logger.error(f"/analyze-channel error: {e}")
        return JSONResponse({"error": "Analysis failed. Please try again."}, status_code=500)

# ─── Trending ─────────────────────────────────────────────────────────────────
@app.get("/trending")
async def trending():
    cached = await redis_get("trending:data")
    if cached:
        try:
            return JSONResponse(json.loads(cached))
        except Exception:
            pass

    async with _trending_lock:
        cached = await redis_get("trending:data")
        if cached:
            try:
                return JSONResponse(json.loads(cached))
            except Exception:
                pass
        try:
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "YouTube trends expert. JSON only."},
                    {"role": "user", "content": (
                        "Generate 16 trending YouTube video topics for Indian creators in 2025. "
                        "Return ONLY a JSON array, no markdown:\n"
                        '[{"niche":"tech","topic":"video idea","why":"why trending now","heat":"🔥"}]\n'
                        "Cover 2 topics each: tech, finance, gaming, fitness, cricket, automobiles, examprep, motivation"
                    )},
                ],
                temperature=0.9,
                max_tokens=1000,
            )
            result = parse_json_safe(response.choices[0].message.content)
            await redis_set("trending:data", json.dumps(result), ex=TRENDING_TTL)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"/trending error: {e}")
            return JSONResponse({"error": "Failed to load trending topics."}, status_code=500)
