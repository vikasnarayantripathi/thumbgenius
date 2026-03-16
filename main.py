import asyncio
"""
ThumbGenius — main.py v4.0
YouTube Packaging Intelligence Platform
7 Modules: Packaging Assistant, Thumbnail Analyzer, CTR Prediction,
           Reverse Engineering, A/B Testing, Inspiration Library, Branding System
"""

from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os, json, asyncio, logging, hashlib, hmac, secrets, base64
from datetime import datetime, timedelta
import httpx

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("thumbgenius")

# ─── ENV ──────────────────────────────────────────────────────────────────────
OPENAI_API_KEY           = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY           = os.getenv("GEMINI_API_KEY","")
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

# ── Stripe (global payments) ───────────────────────────────────────────────
STRIPE_SECRET_KEY       = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CREATOR_PRICE_ID = os.getenv("STRIPE_CREATOR_PRICE_ID", "")   # $19/mo
STRIPE_PRO_PRICE_ID     = os.getenv("STRIPE_PRO_PRICE_ID", "")        # $39/mo

PLAN_LIMITS = {
    "free":       {"generations": 3,    "images": 5,    "thumb_analysis": 1,   "reverse": 2,    "ctr_predict": 0,    "ab_tests": 3,    "blueprint": 1,    "watermark": True,  "hd_images": 0,   "team_seats": 1,  "api_access": False},
    "creator":    {"generations": 500,  "images": 50,   "thumb_analysis": 30,  "reverse": 9999, "ctr_predict": 9999, "ab_tests": 9999, "blueprint": 9999, "watermark": False, "hd_images": 0,   "team_seats": 1,  "api_access": False},
    "pro":        {"generations": 2000, "images": 150,  "thumb_analysis": 100, "reverse": 9999, "ctr_predict": 9999, "ab_tests": 9999, "blueprint": 9999, "watermark": False, "hd_images": 10,  "team_seats": 3,  "api_access": False},
    "enterprise": {"generations": 9999, "images": 500,  "thumb_analysis": 500, "reverse": 9999, "ctr_predict": 9999, "ab_tests": 9999, "blueprint": 9999, "watermark": False, "hd_images": 100, "team_seats": 10, "api_access": True},
}

# Top-up packages (images)
TOPUP_PACKAGES = {
    "topup_10":  {"images": 10,  "price_inr": 49,   "price_usd": 1,  "label": "+10 Images"},
    "topup_30":  {"images": 30,  "price_inr": 99,   "price_usd": 2,  "label": "+30 Images"},
    "topup_100": {"images": 100, "price_inr": 249,  "price_usd": 4,  "label": "+100 Images"},
    "topup_300": {"images": 300, "price_inr": 599,  "price_usd": 8,  "label": "+300 Images"},
}

# Affiliate commission rates
AFFILIATE_RATES = {
    "free":       {"rate": 0.00, "duration_months": 0,  "label": "₹100 flat per paid referral"},
    "creator":    {"rate": 0.20, "duration_months": 6,  "label": "20% recurring for 6 months"},
    "pro":        {"rate": 0.30, "duration_months": 12, "label": "30% recurring for 12 months"},
    "enterprise": {"rate": 0.40, "duration_months": 999,"label": "40% lifetime recurring"},
}
ADMIN_CODES = {"VIKAS2025": {"plans": ["creator", "pro", "enterprise"]}}

def is_admin(code: str) -> bool:
    return code.upper() in ADMIN_CODES
def get_fingerprint(request: Request) -> str:
    """Simple fingerprint from IP + User-Agent for rate limiting."""
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    ip = ip.split(",")[0].strip()
    ua = request.headers.get("user-agent", "")[:50]
    return f"{ip}:{ua}"[:100]
def get_ip(request: Request) -> str:
    """Get client IP from request."""
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    return ip.split(",")[0].strip()



# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ThumbGenius v4.0 — Packaging Intelligence Platform starting...")
    yield
    try:
        await _http_redis.aclose()
        await _http_sb.aclose()
    except Exception:
        pass

app = FastAPI(lifespan=lifespan)
import os as _os
app.mount("/static", StaticFiles(directory=_os.path.join(_os.path.dirname(__file__), "static")), name="static")

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
            "connect-src 'self' https://api.openai.com https://oaidalleapiprodscus.blob.core.windows.net https://api.razorpay.com "
                "https://lumberjack.razorpay.com https://jfestnbagyjrpoczhxbw.supabase.co https://ipapi.co; "
                
                "https://ipapi.co https://generativelanguage.googleapis.com; "
            "frame-src https://api.razorpay.com https://checkout.razorpay.com; "
            "object-src 'none';"
        )
        return response

app.add_middleware(CSPMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://thumbgenius.in", "https://www.thumbgenius.in", "http://localhost:3000", "http://localhost:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-User-Email", "X-Admin-Code"],
)

templates  = Jinja2Templates(directory="templates")
client     = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=1, timeout=20.0)
_http_redis = httpx.AsyncClient(timeout=5.0, verify=False)
_http_sb    = httpx.AsyncClient(timeout=10.0)

# ══════════════════════════════════════════════════════════════════════════════
# INFRASTRUCTURE — Redis, Supabase, Helpers
# ══════════════════════════════════════════════════════════════════════════════

async def redis_get(key):
    try:
        r = await _http_redis.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
        return r.json().get("result")
    except Exception as e:
        logger.warning(f"Redis GET error: {e}"); return None

async def redis_set(key, value, ex=None):
    try:
        cmd = ["SET", key, value]
        if ex: cmd += ["EX", str(ex)]
        await _http_redis.post(
            f"{UPSTASH_REDIS_REST_URL}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            json=cmd)
    except Exception as e:
        logger.warning(f"Redis SET error: {e}")

async def redis_incr(key):
    try:
        r = await _http_redis.get(
            f"{UPSTASH_REDIS_REST_URL}/incr/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
        return r.json().get("result", 1)
    except Exception as e:
        logger.warning(f"Redis INCR error: {e}"); return 1

async def redis_expire(key, seconds):
    try:
        await _http_redis.get(
            f"{UPSTASH_REDIS_REST_URL}/expire/{key}/{seconds}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
    except Exception as e:
        logger.warning(f"Redis EXPIRE error: {e}")

SB_HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


async def redis_del(key):
    try:
        await _http_redis.get(
            f"{UPSTASH_REDIS_REST_URL}/del/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"})
    except Exception as e:
        logger.warning(f"Redis DEL error: {e}")

async def get_user_plan(email: str) -> dict:
    if not email:
        return {"plan": "free"}
    cached = await redis_get(f"plan:{email}")
    if cached:
        try:
            import json as _j
            return _j.loads(cached)
        except Exception:
            pass
    try:
        headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
        r = await _http_sb.get(
            f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}&select=*&limit=1",
            headers=headers)
        if r.status_code == 200:
            rows = r.json()
            if rows:
                import json as _j
                await redis_set(f"plan:{email}", _j.dumps(rows[0]), ex=300)
                return rows[0]
    except Exception as e:
        logger.warning(f"get_user_plan error: {e}")
    return {"plan": "free"}

async def invalidate_plan_cache(email: str):
    if email:
        await redis_del(f"plan:{email}")

async def sb_get_user(email):
    try:
        r = await _http_sb.get(f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}&select=*", headers=SB_HEADERS)
        d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_user: {e}"); return None

async def sb_upsert_user(email, data):
    try:
        payload = {"email": email, **data}
        await _http_sb.post(
            f"{SUPABASE_URL}/rest/v1/users",
            headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates"},
            json=payload)
    except Exception as e:
        logger.error(f"sb_upsert_user: {e}")

async def sb_update_user(email, data):
    try:
        await _http_sb.patch(
            f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}",
            headers=SB_HEADERS, json=data)
    except Exception as e:
        logger.error(f"sb_update_user: {e}")

async def sb_get_user_by_token(token):
    try:
        r = await _http_sb.get(
            f"{SUPABASE_URL}/rest/v1/users?activation_token=eq.{token}&select=*",
            headers=SB_HEADERS)
        d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_user_by_token: {e}"); return None

async def sb_get_user_by_login_token(token):
    try:
        from urllib.parse import quote
        encoded_token = quote(token, safe='')
        r = await _http_sb.get(
            f"{SUPABASE_URL}/rest/v1/users?login_token=eq.{encoded_token}&select=*",
            headers=SB_HEADERS)
        data = r.json()
        logger.info(f"Login token lookup: {len(data)} results for token {token[:10]}...")
        return data[0] if data else None
    except Exception as e:
        logger.error(f"sb_get_user_by_login_token: {e}"); return None

async def sb_get_user_by_subscription(sub_id):
    try:
        r = await _http_sb.get(
            f"{SUPABASE_URL}/rest/v1/users?razorpay_subscription_id=eq.{sub_id}&select=*",
            headers=SB_HEADERS)
        d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_user_by_subscription: {e}"); return None

async def sb_get_brand_kit(email):
    try:
        r = await _http_sb.get(
            f"{SUPABASE_URL}/rest/v1/brand_kits?email=eq.{email}&select=*",
            headers=SB_HEADERS)
        d = r.json(); return d[0] if d else None
    except Exception as e:
        logger.error(f"sb_get_brand_kit: {e}"); return None

async def sb_save_brand_kit(email, kit_data):
    try:
        await _http_sb.post(
            f"{SUPABASE_URL}/rest/v1/brand_kits",
            headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates"},
            json={"email": email, "kit_data": json.dumps(kit_data)})
    except Exception as e:
        logger.error(f"sb_save_brand_kit: {e}")

async def sb_save_inspiration(email, data):
    try:
        await _http_sb.post(
            f"{SUPABASE_URL}/rest/v1/inspiration_saves",
            headers=SB_HEADERS,
            json={"email": email, **data})
    except Exception as e:
        logger.error(f"sb_save_inspiration: {e}")

async def sb_get_inspirations(email):
    try:
        r = await _http_sb.get(
            f"{SUPABASE_URL}/rest/v1/inspiration_saves?email=eq.{email}&select=*&order=created_at.desc",
            headers=SB_HEADERS)
        return r.json()
    except Exception as e:
        logger.error(f"sb_get_inspirations: {e}"); return []


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

# ── Stripe subscription helper ──────────────────────────────────────────────
async def create_stripe_session(plan: str, email: str) -> dict:
    """Create a Stripe Checkout session for global users."""
    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe not configured"}
    price_id = STRIPE_CREATOR_PRICE_ID if plan == "creator" else STRIPE_PRO_PRICE_ID
    if not price_id:
        return {"error": "Stripe price not configured"}
    try:
        r = await _http_sb.post(
            "https://api.stripe.com/v1/checkout/sessions",
            headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"},
            data={
                "mode": "subscription",
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "customer_email": email,
                "success_url": APP_URL + "/activate?session={CHECKOUT_SESSION_ID}&email=" + email + "&plan=" + plan,
                "cancel_url": APP_URL + "/?cancelled=1",
                "metadata[plan]": plan,
                "metadata[email]": email,
            }
        )
        return r.json()
    except Exception as e:
        logger.error(f"Stripe error: {e}")
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# NICHE INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

# ── Creator Language Prompts ──────────────────────────────────────────────────
LANGUAGE_PROMPTS = {
    "english": {
        "instruction": "Generate all content in English. Use global YouTube hooks and patterns.",
        "title_style": "English clickbait with curiosity gap and power words.",
        "overlay_style": "Bold English 3-5 words. Example: THIS CHANGED EVERYTHING",
        "tag_note": "English SEO tags optimised for global YouTube search.",
    },
    "hindi": {
        "instruction": "Generate ALL titles, overlays, hooks, and tags in Hindi (Devanagari script). Use Hindi YouTube culture.",
        "title_style": "Hindi viral titles. Example: यह देखकर हैरान हो जाओगे — curiosity and shock angle.",
        "overlay_style": "Bold Hindi Devanagari 2-4 words. Example: सच्चाई सामने आई",
        "tag_note": "Hindi SEO tags — both Devanagari and Roman transliteration for maximum reach.",
    },
    "hinglish": {
        "instruction": "Generate content in Hinglish — the natural Hindi+English mix used by YouTubers. Mix both naturally.",
        "title_style": "Hinglish style mixing both. Example: Yaar isko dekh ke shock ho gaya! or Maine 10L Kamaye Here is How",
        "overlay_style": "Hinglish 3-5 words. Example: Sach Finally Out! or Bhai Ye Dekh",
        "tag_note": "Mix Hindi + English tags and transliterated keywords for maximum India reach.",
    },
    "telugu": {
        "instruction": "Generate ALL content in Telugu script. Use Telugu YouTube culture, hooks, and expressions.",
        "title_style": "Telugu viral titles with curiosity and shock. Example: ఇది చూసి నోరు తెరుచుకుంటుంది — dramatic revelation style.",
        "overlay_style": "Bold Telugu 2-4 words. Example: నిజం బయటపడింది or షాకింగ్ న్యూస్",
        "tag_note": "Telugu SEO tags — both Telugu script and Roman transliteration for maximum Andhra/Telangana reach.",
    },
    "tamil": {
        "instruction": "Generate ALL content in Tamil script. Use Tamil YouTube culture, kollywood references, and expressions.",
        "title_style": "Tamil viral titles. Example: இதை பார்த்து அதிர்ச்சி ஆனேன் — curiosity and emotion driven.",
        "overlay_style": "Bold Tamil 2-4 words. Example: உண்மை வெளியே or அதிர்ச்சி செய்தி",
        "tag_note": "Tamil SEO tags — Tamil script and Roman transliteration for maximum TN reach.",
    },
    "bengali": {
        "instruction": "Generate ALL content in Bengali script. Use Bengali YouTube culture and expressions.",
        "title_style": "Bengali viral titles. Example: এটা দেখে চমকে গেলাম — shock and curiosity driven.",
        "overlay_style": "Bold Bengali 2-4 words. Example: সত্য প্রকাশ or চমকের খবর",
        "tag_note": "Bengali SEO tags — Bengali script and Roman transliteration for West Bengal and Bangladesh reach.",
    },
    "marathi": {
        "instruction": "Generate ALL content in Marathi script. Use Marathi YouTube culture and expressions.",
        "title_style": "Marathi viral titles. Example: हे पाहून थक्क झालो — shock and curiosity driven.",
        "overlay_style": "Bold Marathi 2-4 words. Example: सत्य समोर or धक्कादायक बातमी",
        "tag_note": "Marathi SEO tags — Marathi script and Roman transliteration for Maharashtra reach.",
    },
}

# ── English / Global niche context ───────────────────────────────────────────
NICHE_CONTEXT_EN = {
    "tech":          "Curiosity gaps, tech specs as hooks, comparison angles. Value-for-money and comparison formats perform well globally.",
    "finance":       "Money amounts, percentage gains/losses, urgency. Investment returns, salary growth, side income.",
    "gaming":        "Challenge framing, game names, rank/level references. Free Fire, BGMI, GTA, Minecraft, Valorant.",
    "fitness":       "Transformation angles, time-based promises. Home workout, no equipment, before/after.",
    "food":          "Sensory words, regional cuisine names. Street food, recipes, restaurant reviews.",
    "travel":        "Discovery angles, budget travel, hidden gems. Off-beat destinations, visa-free, solo travel.",
    "education":     "Skill gaps, career outcomes, time-to-learn. Job market, salary hikes, certifications.",
    "motivation":    "Struggle-to-success arcs, underdog stories. Entrepreneur mindset, discipline, consistency.",
    "beauty":        "Transformation, product comparisons. Affordable dupes, skin tone inclusive, honest reviews.",
    "entertainment": "Controversy, reactions, predictions. OTT reviews, celebrity drama, movie breakdowns.",
    "business":      "Success stories, income figures. Startup ecosystem, solopreneur, passive income.",
    "productivity":  "Time-saving angles, before/after routines. Work smarter, deep work, morning routines.",
    "cricket":       "Match energy, player names, stats. IPL, World Cup, Test cricket references.",
    "automobiles":   "Speed, comparison, value-for-money. EV vs petrol, budget cars, long drive reviews.",
    "examprep":      "Exam strategy, rank mentions, study hacks. Competitive exam preparation tips.",
    "health":        "Transformation, expert-backed claims. Natural remedies, modern medicine, mental health.",
    "pets":          "Cute and emotional. Dog/cat focus. Care tips, breed guides, pet vlogs.",
    "music":         "Genre-specific energy, artist names. Indie, covers, music production, react videos.",
    "realestate":    "Price reveals, location names, investment angle. Property buying, renting tips.",
    "spirituality":  "Calm but impactful. Meditation, yoga, mindfulness, ancient wisdom.",
    "stocks":        "Market movements, portfolio gains. Index funds, trading strategies, passive investing.",
    "cooking":       "Quick recipes, ingredient reveals. Easy meals, healthy cooking, fusion cuisine.",
    "fashion":       "Trend reveals, outfit ideas. Budget fashion, styling tips, seasonal lookbooks.",
    "parenting":     "Child development, parenting hacks. Raising kids, screen time, education at home.",
}

# ── Hindi niche context (deep India cultural references, Devanagari output) ───
NICHE_CONTEXT_HI = {
    "tech":          "जिज्ञासा और तुलना — कौन सा फोन सबसे अच्छा? सस्ते में best performance। OnePlus vs Samsung type hooks।",
    "finance":       "पैसे की बात — SIP, mutual funds, salary tips। ₹ amounts use करें। FOMO और urgency strong काम करती है।",
    "gaming":        "Challenge और rank — Free Fire, BGMI, GTA। गेम के नाम और players के references। Hindi gaming slang।",
    "fitness":       "Transformation — घर पर workout, बिना gym। पहले vs बाद। Desi diet और protein sources।",
    "food":          "खाने की खुशबू और स्वाद — street food, desi recipes, dhaba reviews। Regional cuisine names।",
    "travel":        "अनजानी जगहें — budget travel, hill stations, beaches। सस्ते में घूमो type hooks।",
    "education":     "Career और नौकरी — UPSC, JEE, NEET। Rank, salary hike, certification। Study hacks।",
    "motivation":    "संघर्ष से सफलता — real Indian success stories। Virat, Dhoni, Ratan Tata type references। जिंदगी बदल दो।",
    "beauty":        "Transformation — affordable products, skin whitening myths busted, desi beauty tips। Honest reviews।",
    "entertainment": "Controversy और reactions — Bollywood gossip, OTT reviews, celebrity drama। भाई क्या हो रहा है।",
    "business":      "Business ideas और income — startup, chai pe charcha, small business India। ₹ income figures।",
    "productivity":  "Time management — subah ki routine, deep work, कम समय में ज़्यादा काम। Indian work culture।",
    "cricket":       "Cricket की दीवानगी — IPL, Virat, Rohit, World Cup। Match energy और stats। जीत की खुशी।",
    "automobiles":   "गाड़ी की बात — Maruti vs Hyundai, petrol vs electric, budget cars। Long drive और mileage।",
    "examprep":      "UPSC/JEE/NEET — AIR 1 toppers की strategy। Study schedule, revision tips। सफलता का रास्ता।",
    "health":        "सेहत और तंदुरुस्ती — Ayurveda, home remedies, doctor advice। Weight loss, diabetes, immunity।",
    "pets":          "प्यारे जानवर — dogs और cats। Indian climate के लिए breed tips। Pet care और training।",
    "music":         "संगीत की दुनिया — Bollywood songs, indie artists, music covers। Reactions और behind the scenes।",
    "realestate":    "Property की बात — Mumbai, Delhi, Bangalore। Flat खरीदना या किराया? Investment angle।",
    "spirituality":  "आत्मा की शांति — meditation, yoga, Gita gyaan। Spiritual stories और ancient wisdom।",
    "stocks":        "Share market — Sensex, Nifty, smallcap। Portfolio tips, trading strategy। पैसा काम करे।",
    "cooking":       "रसोई के secrets — quick recipes, desi tadka। Mummy ke haath ka khana type nostalgia।",
    "fashion":       "Style की बात — Indian wedding fashion, budget outfits, seasonal looks। Affordable tips।",
    "parenting":     "बच्चों की परवरिश — Indian family values, screen time, homework help। संस्कार और education।",
}

# ── Hinglish niche context (natural Hindi+English creator mix) ────────────────
NICHE_CONTEXT_HN = {
    "tech":          "Curiosity aur comparison — kaunsa phone best hai? Budget mein best performance. OnePlus vs Samsung type hooks. Hinglish hooks work great.",
    "finance":       "Paisa ki baat — SIP, mutual funds, salary tips. ₹ amounts use karo. FOMO aur urgency strong karti hai. 'Maine itna kamaya' hooks.",
    "gaming":        "Challenge aur rank — Free Fire, BGMI, GTA. Hindi gaming slang mix karo. 'Bhai ye dekh' type energy.",
    "fitness":       "Transformation — ghar pe workout, bina gym. Pehle vs baad. Desi diet aur protein sources Hindi mein.",
    "food":          "Khane ki khushbu aur taste — street food, desi recipes. 'Yaar ye kha ke dekhna' type sensory hooks.",
    "travel":        "Anjani jagahein — budget travel, hill stations. 'Saste mein ghoomo' type hooks. Hinglish works perfectly.",
    "education":     "Career aur job — UPSC, JEE, NEET. Rank, salary hike. 'Ye trick try karo' study hacks.",
    "motivation":    "Sangharsh se safalta — real Indian stories. Virat, Dhoni references. 'Zindagi badal do' energy.",
    "beauty":        "Transformation — affordable products, desi beauty tips. 'Yaar isko try karo' honest reviews.",
    "entertainment": "Controversy aur reactions — Bollywood, OTT reviews. 'Bhai kya ho raha hai' energy.",
    "business":      "Business ideas — startup, small business. '₹ mein kitna kama sakte ho' income reveals.",
    "productivity":  "Time management — subah ki routine, deep work. 'Kam samay mein zyada kaam' hooks.",
    "cricket":       "Cricket ki deewanagi — IPL, Virat, Rohit. Match energy. 'Bhai ye match dekha' reactions.",
    "automobiles":   "Gaadi ki baat — Maruti vs Hyundai, petrol vs electric. 'Bhai ye gaadi leni chahiye' reviews.",
    "examprep":      "UPSC/JEE/NEET prep — toppers ki strategy. 'Ye trick try karo' study hacks in Hinglish.",
    "health":        "Sehat ki baat — Ayurveda meets modern. Home remedies. 'Yaar ye try karo' health tips.",
    "pets":          "Pyare janwar — dogs aur cats. Indian climate tips. 'Mera pet bahut cute hai' type content.",
    "music":         "Music ki duniya — Bollywood, indie. Reactions aur covers. 'Yaar ye sun ke dil bhar aaya' hooks.",
    "realestate":    "Property ki baat — flat kharidna ya kiraya? Investment. 'Bhai ye deal pakad lo' urgency.",
    "spirituality":  "Aatma ki shanti — meditation, yoga, Gita. 'Zindagi mein peace chahiye' hooks.",
    "stocks":        "Share market — Sensex, Nifty. 'Bhai ye stocks dekh' portfolio tips in Hinglish.",
    "cooking":       "Rasoi ke secrets — quick recipes, desi tadka. 'Mummy ke haath ka khana' nostalgia hooks.",
    "fashion":       "Style ki baat — Indian wedding fashion, budget outfits. 'Bhai ye outfit try karo' hooks.",
    "parenting":     "Bacchon ki parvarish — Indian family values, screen time. 'Aaj kal ke bacche' hooks.",
}

# ── Default fallback (keeps backward compat) ─────────────────────────────────
NICHE_CONTEXT = NICHE_CONTEXT_EN

def get_generate_prompt(topic, niche, language="english"):
    # Pick language-specific niche context
    ctx_map = {"hindi": NICHE_CONTEXT_HI, "hinglish": NICHE_CONTEXT_HN, "telugu": NICHE_CONTEXT_HI, "tamil": NICHE_CONTEXT_HI, "bengali": NICHE_CONTEXT_HI, "marathi": NICHE_CONTEXT_HI}
    ctx  = ctx_map.get(language, NICHE_CONTEXT_EN)
    tip  = ctx.get(niche, ctx.get("tech", ""))
    lang = LANGUAGE_PROMPTS.get(language, LANGUAGE_PROMPTS["english"])
    return f"""You are a world-class YouTube growth strategist with expertise across global markets.

Video Topic: "{topic}"
Niche: {niche}
Niche Strategy: {tip}

LANGUAGE: {language.upper()}
Language Instruction: {lang["instruction"]}
Title Style: {lang["title_style"]}
Text Overlay Style: {lang["overlay_style"]}
Tag Note: {lang["tag_note"]}

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
  "niche_tip": "One tactical tip for this niche on YouTube right now.",
  "seo_description": "150-200 word YouTube description. Start with the primary keyword. Include 3-5 natural keyword variations. Add value with what viewers will learn. End with call-to-action and 3 relevant hashtags. Write in the selected language.",
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


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Privacy Policy - ThumbGenius</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{background:#02020A;color:#fff;font-family:'Plus Jakarta Sans',sans-serif;max-width:800px;margin:0 auto;padding:40px 24px;line-height:1.8}h1{color:#FFE036;font-size:32px}h2{color:rgba(255,255,255,0.8);font-size:20px;margin-top:32px}p,li{color:rgba(255,255,255,0.6);font-size:15px}a{color:#FFE036}header{margin-bottom:40px}footer{margin-top:60px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.1);text-align:center;font-size:13px;color:rgba(255,255,255,0.3)}</style></head><body><header><a href="/" style="color:#FFE036;text-decoration:none;font-size:14px">← Back to ThumbGenius</a><h1>Privacy Policy</h1><p>Last updated: January 2025</p></header><h2>Information We Collect</h2><p>We collect your email address when you subscribe or log in. We store the topics and niches you generate content for to serve your requests. We do not collect payment information directly — payments are processed by Razorpay and Stripe.</p><h2>How We Use Your Information</h2><p>Your email is used to send magic login links and plan activation emails. Your usage data (generations, images used) is stored to enforce plan limits. We do not sell or share your data with third parties.</p><h2>Data Storage</h2><p>Your data is stored securely in Supabase (PostgreSQL) with encrypted connections. We retain data for as long as your account is active.</p><h2>Cookies</h2><p>We use localStorage in your browser to remember your login state and preferences. No third-party tracking cookies are used.</p><h2>Contact</h2><p>For privacy concerns, email us at <a href="mailto:support@thumbgenius.in">support@thumbgenius.in</a>.</p><footer>© 2025 ThumbGenius · <a href="/">Home</a> · <a href="/terms">Terms</a> · <a href="/refund">Refund</a></footer></body></html>""")

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Terms of Service - ThumbGenius</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{background:#02020A;color:#fff;font-family:'Plus Jakarta Sans',sans-serif;max-width:800px;margin:0 auto;padding:40px 24px;line-height:1.8}h1{color:#FFE036;font-size:32px}h2{color:rgba(255,255,255,0.8);font-size:20px;margin-top:32px}p,li{color:rgba(255,255,255,0.6);font-size:15px}a{color:#FFE036}header{margin-bottom:40px}footer{margin-top:60px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.1);text-align:center;font-size:13px;color:rgba(255,255,255,0.3)}</style></head><body><header><a href="/" style="color:#FFE036;text-decoration:none;font-size:14px">← Back to ThumbGenius</a><h1>Terms of Service</h1><p>Last updated: January 2025</p></header><h2>Acceptance of Terms</h2><p>By using ThumbGenius, you agree to these terms. If you do not agree, please do not use our service.</p><h2>Use of Service</h2><p>ThumbGenius provides AI-powered YouTube content tools. You agree to use the service only for lawful purposes and not to generate content that is harmful, misleading, or violates YouTube's community guidelines.</p><h2>Subscriptions & Billing</h2><p>Paid plans are billed monthly. You can cancel anytime by contacting support@thumbgenius.in. Cancellations take effect at the end of the current billing period.</p><h2>Intellectual Property</h2><p>Content generated by ThumbGenius using your inputs belongs to you. ThumbGenius retains rights to its platform, code, and branding.</p><h2>Limitation of Liability</h2><p>ThumbGenius is provided "as is". We are not liable for any indirect or consequential damages arising from use of the service.</p><h2>Contact</h2><p>Email: <a href="mailto:support@thumbgenius.in">support@thumbgenius.in</a></p><footer>© 2025 ThumbGenius · <a href="/">Home</a> · <a href="/privacy">Privacy</a> · <a href="/refund">Refund</a></footer></body></html>""")

@app.get("/refund", response_class=HTMLResponse)
async def refund(request: Request):
    return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Refund Policy - ThumbGenius</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{background:#02020A;color:#fff;font-family:'Plus Jakarta Sans',sans-serif;max-width:800px;margin:0 auto;padding:40px 24px;line-height:1.8}h1{color:#FFE036;font-size:32px}h2{color:rgba(255,255,255,0.8);font-size:20px;margin-top:32px}p,li{color:rgba(255,255,255,0.6);font-size:15px}a{color:#FFE036}header{margin-bottom:40px}footer{margin-top:60px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.1);text-align:center;font-size:13px;color:rgba(255,255,255,0.3)}</style></head><body><header><a href="/" style="color:#FFE036;text-decoration:none;font-size:14px">← Back to ThumbGenius</a><h1>Refund Policy</h1><p>Last updated: January 2025</p></header><h2>7-Day Refund Guarantee</h2><p>We offer a full refund within 7 days of your first payment if you are not satisfied with ThumbGenius. No questions asked.</p><h2>How to Request a Refund</h2><p>Email us at <a href="mailto:support@thumbgenius.in">support@thumbgenius.in</a> with your registered email and reason. We will process the refund within 5-7 business days to your original payment method.</p><h2>Exceptions</h2><p>Refunds are not available after 7 days of purchase, or if the account has been found to violate our Terms of Service.</p><h2>Subscription Cancellations</h2><p>Cancelling a subscription stops future billing but does not automatically trigger a refund for the current period. Contact us if you need a refund for the current period.</p><h2>Contact</h2><p>Email: <a href="mailto:support@thumbgenius.in">support@thumbgenius.in</a></p><footer>© 2025 ThumbGenius · <a href="/">Home</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></footer></body></html>""")

@app.get("/landing")
async def landing_page(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE OAUTH
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/auth/google")
async def auth_google():
    """Redirect to Supabase Google OAuth"""
    from urllib.parse import urlencode, quote
    params = urlencode({
        "provider": "google",
        "redirect_to": f"{APP_URL}/auth/callback"
    })
    supabase_oauth_url = f"{SUPABASE_URL}/auth/v1/authorize?{params}"
    logger.info(f"OAuth redirect to: {supabase_oauth_url}")
    return RedirectResponse(supabase_oauth_url)

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", error: str = ""):
    """Handle OAuth callback from Supabase"""
    if error:
        logger.error(f"OAuth error: {error}")
        return RedirectResponse(f"{APP_URL}/landing?msg=oauth_error")
    if not code:
        return RedirectResponse(f"{APP_URL}/landing?msg=oauth_error")
    try:
        # Exchange code for session
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Content-Type": "application/json"
                },
                json={"auth_code": code, "code_verifier": ""}
            )
            data = r.json()

        if "error" in data:
            # Try alternative exchange
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{SUPABASE_URL}/auth/v1/token?grant_type=authorization_code",
                    headers={
                        "apikey": SUPABASE_KEY,
                        "Content-Type": "application/json"
                    },
                    json={"code": code}
                )
                data = r.json()

        email = data.get("user", {}).get("email", "")
        if not email:
            logger.error(f"OAuth callback no email: {data}")
            return RedirectResponse(f"{APP_URL}/landing?msg=oauth_error")

        # Upsert user in our users table
        existing = await sb_get_user(email)
        if not existing:
            await sb_create_user(email)
            logger.info(f"OAuth: new user created {email}")
        else:
            logger.info(f"OAuth: existing user logged in {email}")

        # Clear plan cache
        await redis_del(f"plan:{email}")

        # Redirect to app with email as session param
        import urllib.parse
        return RedirectResponse(f"{APP_URL}/?login=1&email={urllib.parse.quote(email)}")

    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return RedirectResponse(f"{APP_URL}/landing?msg=oauth_error")

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
    email          = str(data.get("email", "")).strip().lower()
    plan           = str(data.get("plan", "")).strip().lower()
    payment_method = str(data.get("payment_method", "razorpay")).strip().lower()
    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    if plan not in ["creator", "pro", "enterprise"]:
        return JSONResponse({"error": "Invalid plan"}, status_code=400)

    # ── Stripe (global users) ──────────────────────────────────────────────
    if payment_method == "stripe":
        session = await create_stripe_session(plan, email)
        if "error" in session:
            return JSONResponse({"error": session["error"]}, status_code=500)
        token = secrets.token_urlsafe(32)
        await sb_upsert_user(email, {"plan": plan, "stripe_session_id": session.get("id",""),
                                      "activation_token": token, "is_active": False})
        return JSONResponse({"payment_method": "stripe",
                             "checkout_url": session.get("url", ""),
                             "session_id": session.get("id", ""),
                             "plan": plan, "email": email})

    # ── Razorpay (India users) ─────────────────────────────────────────────
    sub = await create_razorpay_subscription(plan, email)
    if not sub or "id" not in sub:
        return JSONResponse({"error": "Payment setup failed."}, status_code=500)
    token = secrets.token_urlsafe(32)
    await sb_upsert_user(email, {"plan": plan, "razorpay_subscription_id": sub["id"],
                                  "activation_token": token, "is_active": False})
    return JSONResponse({"payment_method": "razorpay",
                         "subscription_id": sub["id"], "razorpay_key": RAZORPAY_KEY_ID,
                         "plan": plan, "email": email,
                         "amount": 74900 if plan == "creator" else 144900})

# ─── Activate ─────────────────────────────────────────────────────────────────
@app.get("/activate", response_class=HTMLResponse)
async def activate(request: Request, token: str = "", login_token: str = ""):
    from datetime import timezone as _tz

    # ── Magic link login flow ──────────────────────────────────
    if login_token:
        user = await sb_get_user_by_login_token(login_token)
        if not user:
            return HTMLResponse("<h1>Login link expired or invalid. Please request a new one.</h1>", status_code=400)
        # Check expiry
        expires = user.get("login_token_expires")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if datetime.now(_tz.utc) > exp_dt:
                    return HTMLResponse("<h1>Login link expired. Please request a new one.</h1>", status_code=400)
            except: pass
        await sb_update_user(user["email"], {"login_token": None, "login_token_expires": None})
        await invalidate_plan_cache(user["email"])
        plan = user.get("plan", "free")
        return HTMLResponse(f"""<!DOCTYPE html><html><head><title>Logged In!</title>
        <style>body{{font-family:Arial;background:#02020A;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
        .box{{text-align:center;padding:40px}}h1{{color:#FDE036}}p{{color:#aaa}}</style>
        </head><body><div class="box"><h1>✅ Logged In!</h1><p>Welcome back, <strong>{user["email"]}</strong></p>
        <p>Plan: <strong style="color:#FDE036">{plan.upper()}</strong></p>
        <p>Redirecting...</p></div>
        <script>
            localStorage.setItem('tg_email','{user["email"]}');
            localStorage.setItem('tg_plan','{plan}');
            localStorage.setItem('tg_entered_app','1');
            localStorage.setItem('tg_last_active', Date.now().toString());
            localStorage.removeItem('tg_trial_start');
            setTimeout(function(){{ window.location.href = '/?login=1'; }}, 1500);
        </script></body></html>""")

    # ── Payment activation flow ────────────────────────────────
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

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe subscription events."""
    try:
        body      = await request.body()
        sig       = request.headers.get("Stripe-Signature", "")
        if STRIPE_WEBHOOK_SECRET and sig:
            import time as _t
            parts    = dict(kv.split("=",1) for kv in sig.split(",") if "=" in kv)
            ts       = parts.get("t","0")
            v1_sig   = parts.get("v1","")
            payload  = f"{ts}.{body.decode()}"
            expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, v1_sig):
                logger.warning("Stripe signature mismatch")
                return JSONResponse({"status": "ok"})

        event      = json.loads(body)
        event_type = event.get("type","")
        logger.info(f"Stripe webhook: {event_type}")

        if event_type in ("customer.subscription.created","customer.subscription.updated",
                          "invoice.payment_succeeded"):
            obj   = event.get("data",{}).get("object",{})
            meta  = obj.get("metadata",{})
            email = obj.get("customer_email") or meta.get("email","")
            plan  = meta.get("plan","")
            if email and plan:
                await sb_upsert_user(email, {"plan": plan, "is_active": True,
                    "stripe_subscription_id": obj.get("subscription", obj.get("id","")),
                    "generations_used": 0, "images_used": 0})
                await invalidate_plan_cache(email)
                if event_type == "customer.subscription.created":
                    token = secrets.token_urlsafe(32)
                    await sb_update_user(email, {"activation_token": token})
                    asyncio.create_task(send_magic_link(email, token, plan))

        elif event_type == "customer.subscription.deleted":
            obj   = event.get("data",{}).get("object",{})
            meta  = obj.get("metadata",{})
            email = meta.get("email","")
            if email:
                await sb_update_user(email, {"plan":"free","is_active":False})
                await invalidate_plan_cache(email)

    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
    return JSONResponse({"status": "ok"})

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 7 — PACKAGING ASSISTANT (generate + generate-image)
# ══════════════════════════════════════════════════════════════════════════════


# ── User Usage Stats ─────────────────────────────────────────────────────────
@app.get("/user/usage")
async def user_usage(request: Request):
    email      = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm     = is_admin(admin_code)
    if not email and not is_adm:
        return JSONResponse({"error":"not_logged_in"}, status_code=401)
    if is_adm and not email:
        return JSONResponse({"plan":"enterprise","email":"admin","limits":PLAN_LIMITS["enterprise"],
                             "topup_images":0,
                             "used":{"generations":0,"images":0,"thumb_analysis":0,
                                     "reverse":0,"ctr_predict":0,"ab_tests":0,"blueprint":0}})
    pd = await get_user_plan(email)
    plan = pd.get("plan","free")
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    used = {
        "generations":    pd.get("generations_used",0),
        "images":         pd.get("images_used",0),
        "thumb_analysis": pd.get("thumb_analysis_used",0),
        "reverse":        pd.get("reverse_used",0),
        "ctr_predict":    pd.get("ctr_predict_used",0),
        "ab_tests":       pd.get("ab_tests_used",0),
        "blueprint":      pd.get("blueprint_used",0),
    }
    return JSONResponse({"plan":plan,"email":email,"limits":limits,"used":used,
                         "topup_images": pd.get("topup_images",0)})

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
    topic    = str(data.get("topic","")).strip()
    niche    = str(data.get("niche","tech")).strip()
    language = str(data.get("language","english")).strip().lower()
    if language not in ("english","hindi","hinglish"): language = "english"
    if not topic: return JSONResponse({"error":"Please enter a video topic"},status_code=400)
    if len(topic) > 300: return JSONResponse({"error":"Topic too long"},status_code=400)
    cached = await get_generation_cache(topic, niche)
    if cached:
        if not is_adm:
            if email: asyncio.create_task(sb_update_user(email,{"generations_used":used+1})); asyncio.create_task(invalidate_plan_cache(email))
            else: asyncio.create_task(increment_free_limit(request))
        cached["from_cache"] = True; return JSONResponse(cached)
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"system","content":"You are a YouTube growth expert. Return ONLY valid JSON, no markdown, no explanation."},
                          {"role":"user","content":get_generate_prompt(topic,niche,language)}],
                temperature=0.8, max_tokens=1800),
            timeout=20.0)
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
    except asyncio.TimeoutError:
        logger.error("/generate timeout after 20s")
        return JSONResponse({"error":"AI is taking too long. Please try again."},status_code=504)
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
    language = str(data.get("language","english")).strip().lower()
    no_baked_text = bool(data.get("no_baked_text", False))
    custom_image_b64 = data.get("custom_image_b64", None)
    custom_image_mode = str(data.get("custom_image_mode", "")).strip()
    if not concept: return JSONResponse({"error":"No concept provided"},status_code=400)
    try:
        overlay_spelled = " ".join(list(overlay.upper())) if overlay else ""
        niche = str(data.get("niche","")).strip()
        img_prompt = (
            f"YouTube thumbnail, 16:9 widescreen, photorealistic 8K. "
            f"EXACT SCENE TO RECREATE: {concept}. "
            f"Do NOT add random props. Only show what is described in the scene above. "
            f"Person: Indian/South Asian, highly expressive face matching the emotion in the scene. "
            f"Style: ultra-vibrant oversaturated colors, dramatic cinematic lighting, MrBeast quality. "
            f"Composition: person face prominent on one side, background scene clearly visible. "
            f"CRITICAL: zero text, zero letters, zero words, zero watermarks, zero logos. No exceptions."
        )

        # If custom image provided — use Gemini Vision to generate around it
        if custom_image_b64 and custom_image_mode == "generate":
            import base64 as _b64
            gemini_vision_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
            vision_prompt = f"You are a YouTube thumbnail designer. Based on this photo, create a detailed image generation prompt for a viral YouTube thumbnail. The thumbnail is about: {concept}. Style: {img_prompt} Describe exactly how to incorporate the person/subject from this photo into the thumbnail."
            vision_payload = {
                "contents": [{
                    "parts": [
                        {"text": vision_prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": custom_image_b64}}
                    ]
                }]
            }
            async with httpx.AsyncClient(timeout=30.0) as hv:
                vr = await hv.post(gemini_vision_url, json=vision_payload)
            if vr.status_code == 200:
                vdata = vr.json()
                enhanced_prompt = vdata.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if enhanced_prompt:
                    img_prompt = enhanced_prompt[:2000]
        # Use Gemini Imagen 3
        import base64 as _b64
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict?key={GEMINI_API_KEY}"
        payload = {
            "instances": [{"prompt": img_prompt[:2000]}],
            "parameters": {"sampleCount": 1, "aspectRatio": "16:9", "personGeneration": "allow_adult"}
        }
        # DALL-E 3 primary — best for YouTube thumbnails (follows prompts accurately)
        img_b64 = None
        use_hd = bool(data.get("hd_mode", False))

        # HD mode = DALL-E 3 (costs 2 image credits, Pro/Enterprise only)
        if use_hd and plan_for_wm in ("pro", "enterprise"):
            try:
                dalle_resp = await client.images.generate(
                    model="dall-e-3",
                    prompt=img_prompt[:4000],
                    size="1792x1024",
                    quality="hd",
                    n=1,
                    response_format="b64_json"
                )
                img_b64 = dalle_resp.data[0].b64_json
                logger.info("DALL-E 3 HD generated successfully")
            except Exception as de:
                logger.warning(f"DALL-E 3 HD failed: {de} — falling back to Imagen")

        # Standard mode = Imagen 4 Fast (primary, cheap)
        if not img_b64:
            try:
                async with httpx.AsyncClient(timeout=60.0) as hc:
                    r = await hc.post(gemini_url, json=payload)
                if r.status_code == 200:
                    rdata = r.json()
                    predictions = rdata.get("predictions")
                    if predictions and len(predictions) > 0:
                        img_b64 = predictions[0]["bytesBase64Encoded"]
                        logger.info("Imagen 4 Fast generated successfully")
            except Exception as ie:
                logger.warning(f"Imagen 4 Fast failed: {ie} — trying DALL-E 3 fallback")

        # Final fallback = DALL-E 3 standard
        if not img_b64:
            try:
                dalle_resp = await client.images.generate(
                    model="dall-e-3",
                    prompt=img_prompt[:4000],
                    size="1792x1024",
                    quality="standard",
                    n=1,
                    response_format="b64_json"
                )
                img_b64 = dalle_resp.data[0].b64_json
                logger.info("DALL-E 3 fallback generated successfully")
            except Exception as de:
                logger.warning(f"DALL-E 3 fallback also failed: {de}")
        if not is_adm:
            if email:
                asyncio.create_task(sb_update_user(email,{"images_used":used+1}))
                asyncio.create_task(invalidate_plan_cache(email))
            else:
                img_key2 = f"img:{hashlib.md5(get_ip(request).encode()).hexdigest()[:16]}"
                cnt2 = await redis_incr(img_key2)
                if cnt2 == 1: await redis_expire(img_key2, 30*24*3600)
        if not img_b64:
            return JSONResponse({"error": "Image generation failed. Please try again."}, status_code=500)
        # Apply watermark for free users
        plan_for_wm = "free"
        if is_adm:
            plan_for_wm = "pro"
        elif email:
            plan_for_wm = pd.get("plan", "free")
        if PLAN_LIMITS.get(plan_for_wm, PLAN_LIMITS["free"]).get("watermark", False):
            try:
                from PIL import Image, ImageDraw, ImageFont
                import io, base64 as _b64wm
                img_bytes = _b64.b64decode(img_b64)
                img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                W, H = img.size
                draw = ImageDraw.Draw(img)
                wm_text = "ThumbGenius.in"
                font_size = max(20, W // 35)
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except:
                    font = ImageFont.load_default()
                bbox = draw.textbbox((0, 0), wm_text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x, y = W - tw - 20, H - th - 20
                # Shadow
                draw.text((x+2, y+2), wm_text, font=font, fill=(0, 0, 0, 180))
                # Text
                draw.text((x, y), wm_text, font=font, fill=(255, 224, 54, 220))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=92)
                img_b64 = _b64.b64encode(buf.getvalue()).decode()
            except Exception as wm_err:
                logger.warning(f"Watermark error: {wm_err}")
        remaining = 9999 if is_adm else max(0, limit-used-1)
        return JSONResponse({"image_b64": img_b64, "images_remaining": remaining, "watermarked": PLAN_LIMITS.get(plan_for_wm, PLAN_LIMITS["free"]).get("watermark", False)})
    except Exception as e:
        logger.error(f"/generate-image error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)

@app.get("/image-data/{img_id}")
async def image_data(img_id: str):
    img_b64 = await redis_get(f"img_data:{img_id}")
    if not img_b64:
        return JSONResponse({"error": "Image expired or not found"}, status_code=404)
    import base64 as _b64
    img_bytes = _b64.b64decode(img_b64)
    from fastapi.responses import Response
    return Response(content=img_bytes, media_type="image/png")


@app.get("/image-status/{job_id}")
async def image_status(job_id: str):
    val = await redis_get(f"imgjob:{job_id}")
    if not val:
        return JSONResponse({"status":"not_found"}, status_code=404)
    if val == "pending":
        return JSONResponse({"status":"pending"})
    if val.startswith("done:"):
        return JSONResponse({"status":"done","image_url":val[5:]})
    if val.startswith("error:"):
        return JSONResponse({"status":"error","message":val[6:]})
    return JSONResponse({"status":"pending"})


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
    prompt = f"""You are a YouTube CTR prediction expert with deep knowledge of global YouTube trends.
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
                {"role":"user","content":f'Compare these YouTube titles for the target audience. JSON only.\nTitle A: "{title_a}"\nTitle B: "{title_b}"\nReturn: {{"winner":"A or B","score_a":8,"score_b":7,"reasoning":"2-3 sentences","emotional_angle_a":"Curiosity Gap","emotional_angle_b":"Shock Factor","improvement_a":"one specific fix for title A","improvement_b":"one specific fix for title B"}}'}
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
    prompt = f"""You are a YouTube A/B testing expert for global YouTube audiences.
Compare these two thumbnails for a {niche} channel.
{f'Thumbnail A title: "{title_a}"' if title_a else ''}
{f'Thumbnail B title: "{title_b}"' if title_b else ''}

Simulate how YouTube viewers would respond to each thumbnail.
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
  "audience_segment_notes": "How different audience segments (mobile-first, age 18-24 vs 25-35) might respond differently."
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
    prompt = f"""Generate 6 high-performing YouTube thumbnail concepts for the Inspiration Library.
{niche_filter} {trigger_filter} Focus on global YouTube trends (2024-2025).

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
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"system","content":"YouTube thumbnail expert. Return ONLY a valid JSON array, no markdown."},
                          {"role":"user","content":prompt}],
                temperature=0.9, max_tokens=1500),
            timeout=25
        )
        result = parse_json_safe(response.choices[0].message.content)
        if not isinstance(result, list): result = result.get("items", result.get("thumbnails", []))
        await redis_set(cache_key, json.dumps(result), ex=3600)
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "timeout"}, status_code=500)
    except Exception as e:
        logger.error(f"/inspiration/library error: {type(e).__name__}: {e}")
        return JSONResponse({"error": f"Failed to load library: {type(e).__name__}"},status_code=500)

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
    email      = request.headers.get("X-User-Email","").strip().lower()
    admin_code = request.headers.get("X-Admin-Code","").strip().upper()
    is_adm     = is_admin(admin_code)
    # Determine plan
    if is_adm:
        plan = "pro"
    elif email:
        pd   = await get_user_plan(email)
        plan = pd.get("plan","free")
    else:
        plan = "free"

    try: data = await request.json()
    except: return JSONResponse({"error":"Invalid request"},status_code=400)
    titles = str(data.get("titles","")).strip()
    niche  = str(data.get("niche","tech")).strip()
    if not titles: return JSONResponse({"error":"Please enter your video titles"},status_code=400)

    # Tier config
    if plan == "pro" or is_adm:
        model       = "gpt-4o-mini"
        max_tokens  = 2000
        title_ideas = 10
        tier_label  = "10X Pro"
    elif plan == "creator":
        model       = "gpt-4o-mini"
        max_tokens  = 1500
        title_ideas = 5
        tier_label  = "5X Creator"
    else:
        model       = "gpt-4o-mini"
        max_tokens  = 800
        title_ideas = 0
        tier_label  = "Basic"

    prompt = f"""You are a YouTube channel growth expert and packaging strategist.
Analyze these YouTube video titles from a creator in the {niche} niche:
"{titles}"

Return ONLY valid JSON (no markdown):
{{
  "overall_grade": "B+",
  "overall_score": 72,
  "packaging_dna": "Your titles follow a [pattern] style — mostly [type]. You rely heavily on [pattern] but rarely use [missing pattern].",
  "scores": {{
    "ctr_power":     {{"score": 70, "label": "Good",   "note": "specific observation"}},
    "emotion":       {{"score": 60, "label": "Average","note": "specific observation"}},
    "clarity":       {{"score": 80, "label": "Strong", "note": "specific observation"}},
    "curiosity_gap": {{"score": 55, "label": "Weak",   "note": "specific observation"}},
    "consistency":   {{"score": 75, "label": "Good",   "note": "specific observation"}}
  }},
  "best_title":  {{"title": "the best title from the list", "reason": "why it works"}},
  "worst_title": {{"title": "the worst title from the list", "reason": "why it fails"}},
  "patterns": [
    {{"pattern": "Pattern name", "frequency": "70%", "impact": "positive/negative", "note": "explanation"}}
  ],
  "missing_patterns": ["curiosity gap", "number hooks", "emotional triggers"],
  "issues": [
    {{"title": "Issue name", "detail": "Specific explanation with example from their titles"}}
  ],
  "fixes": [
    {{"title": "Fix name", "detail": "Specific actionable fix", "example": "Before: X → After: Y"}}
  ],
  "rewrites": [
    {{"original": "their title", "improved": "10x better version", "why": "what makes it better"}}
  ],
  "title_ideas": [
    {{"title": "AI-generated title idea for their niche", "hook_type": "curiosity/emotion/number/shock"}}
  ],
  "competitor_benchmark": {{
    "their_score": 72,
    "top_creator_score": 88,
    "gap": 16,
    "top_creator_habit": "Top {niche} creators use curiosity gaps 3x more and lead with numbers"
  }},
  "verdict": "2-3 sentence overall channel packaging verdict"
}}
Rules:
- title_ideas: generate exactly 10 title ideas specific to their niche and style
- rewrites: rewrite ALL titles provided, one by one
- Be specific, reference their actual titles in feedback
- patterns: identify 2-3 patterns you see in their titles"""

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system","content":"YouTube packaging expert. Return ONLY valid JSON, no markdown."},
                    {"role":"user","content":prompt}
                ],
                temperature=0.7, max_tokens=2500,
                response_format={"type": "json_object"}
            ),
            timeout=25
        )
        result = parse_json_safe(response.choices[0].message.content)
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error":"Analysis taking too long. Please try again."}, status_code=504)
    except Exception as e:
        logger.error(f"/analyze-channel error: {e}"); return JSONResponse({"error":"Analysis failed."},status_code=500)

@app.get("/trending")
async def trending(request: Request, niches: str = ""):
    # Parse requested niches
    VALID_NICHES = {"tech","finance","gaming","fitness","food","travel","education","motivation",
                    "beauty","entertainment","business","productivity","cricket","automobiles",
                    "examprep","health","music","realestate","spirituality","stocks",
                    "cooking","comedy","news","astrology","relationship","parenting",
                    "fashion","mythology","selfdevelopment","career"}
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
            prompt = f"""Generate {total} trending YouTube video topics for creators right now in 2025.
Niches requested: {niche_list}
Generate exactly {per_niche} topics per niche.

Return a JSON object with a "topics" key containing an array:
{{"topics": [
  {{"niche":"tech","topic":"Specific compelling video title","why":"One sentence why this is trending right now","heat":"🔥🔥 High Momentum"}},
  ...
]}}

Rules:
- Topics must be specific, actionable video title ideas (not generic)
- Highly relevant to the {niche_list} YouTube audience in 2025
- Each topic must have all 4 fields: niche, topic, why, heat
- niche must exactly match one of: {niche_list}"""

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system","content":"YouTube trends expert for global creators. Return only valid JSON."},
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

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 8 — VIRAL THUMBNAIL BLUEPRINT
# ══════════════════════════════════════════════════════════════════════════════

import re as _re

PLAN_LIMITS["free"]["blueprint"]    = 1
PLAN_LIMITS["creator"]["blueprint"] = 10
PLAN_LIMITS["pro"]["blueprint"]     = 999

def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from any YouTube URL format."""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/v/([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = _re.search(p, url)
        if m:
            return m.group(1)
    return None

async def fetch_youtube_thumbnail_b64(video_id: str) -> tuple[str, str]:
    """
    Try maxresdefault → hqdefault → mqdefault.
    Returns (base64_string, thumbnail_url).
    """
    qualities = ["maxresdefault", "hqdefault", "mqdefault"]
    async with httpx.AsyncClient(timeout=10.0) as h:
        for q in qualities:
            url = f"https://img.youtube.com/vi/{video_id}/{q}.jpg"
            try:
                r = await h.get(url)
                if r.status_code == 200 and len(r.content) > 5000:
                    b64 = base64.b64encode(r.content).decode()
                    return b64, url
            except Exception:
                continue
    raise ValueError("Could not fetch thumbnail for this video.")

NICHE_BENCHMARKS = {
    "tech": 72, "finance": 68, "gaming": 78, "fitness": 74,
    "food": 70, "travel": 71, "education": 65, "motivation": 76,
    "beauty": 73, "entertainment": 75, "business": 67, "productivity": 64,
    "cricket": 69, "automobiles": 70, "examprep": 63, "health": 66,
    "music": 72, "realestate": 61, "spirituality": 64, "stocks": 65,
    "cooking": 70, "comedy": 77, "news": 66, "astrology": 68,
    "relationship": 71, "parenting": 67, "fashion": 74, "mythology": 69,
    "selfdevelopment": 73, "career": 65
}

BLUEPRINT_SCORE_PROMPT = """You are an expert YouTube CTR analyst with deep knowledge of viewer psychology.
Analyze this YouTube thumbnail image and score it across 7 dimensions.

Return ONLY valid JSON — no markdown, no explanation outside JSON:
{{
  "overall_score": 74,
  "grade": "B+",
  "scores": {{
    "emotion_strength":     {{ "score": 80, "label": "Strong", "note": "One sentence specific to this thumbnail" }},
    "subject_size":         {{ "score": 65, "label": "Medium", "note": "..." }},
    "color_contrast":       {{ "score": 90, "label": "Excellent", "note": "..." }},
    "text_readability":     {{ "score": 55, "label": "Weak", "note": "..." }},
    "curiosity_trigger":    {{ "score": 78, "label": "Strong", "note": "..." }},
    "composition_balance":  {{ "score": 70, "label": "Good", "note": "..." }},
    "mobile_visibility":    {{ "score": 60, "label": "Needs Work", "note": "..." }}
  }},
  "verdict": "2-3 sentence summary of why this thumbnail works or fails overall.",
  "strongest_element": "One specific thing done best",
  "biggest_weakness": "The single most damaging issue",
  "attention_zones": [
    {{ "region": "top-left",    "weight": 10 }},
    {{ "region": "top-center",  "weight": 25 }},
    {{ "region": "top-right",   "weight": 15 }},
    {{ "region": "mid-left",    "weight": 5  }},
    {{ "region": "mid-center",  "weight": 30 }},
    {{ "region": "mid-right",   "weight": 20 }},
    {{ "region": "bot-left",    "weight": 5  }},
    {{ "region": "bot-center",  "weight": 15 }},
    {{ "region": "bot-right",   "weight": 10 }}
  ],
  "fixes": [
    {{ "dimension": "text_readability", "priority": 1, "action": "Specific actionable fix for the worst dimension" }},
    {{ "dimension": "subject_size",     "priority": 2, "action": "..." }},
    {{ "dimension": "mobile_visibility","priority": 3, "action": "..." }}
  ]
}}

Scoring guide:
- emotion_strength (weight 20%): Face expression intensity, emotional clarity, human connection
- subject_size (weight 10%): Is the main subject large enough to read at small size
- color_contrast (weight 15%): Background vs foreground contrast, eye-catching palette
- text_readability (weight 15%): Font size, color, stroke, legibility at 120px width
- curiosity_trigger (weight 20%): Information gap, tension, intrigue, FOMO signals
- composition_balance (weight 5%): Visual weight distribution, rule of thirds
- mobile_visibility (weight 15%): Overall clarity at 120x68px (mobile feed size)

overall_score = weighted average using above percentages.
grade: 90-100=A+, 80-89=A, 70-79=B+, 60-69=B, 50-59=C, below 50=F
Niche context: {niche}"""

BLUEPRINT_VARIATIONS_PROMPT = """You are a top YouTube thumbnail designer.
Based on this thumbnail analysis, generate {count} DALL-E 3 prompts for improved thumbnail variations.

Original thumbnail scores:
{scores_summary}

Biggest weakness: {biggest_weakness}
Niche: {niche}
Video topic context: {topic_context}

Generate exactly {count} variation prompts. Each should target a specific improvement.
Return ONLY valid JSON:
{{
  "variations": [
    {{
      "variation_number": 1,
      "targets": "emotion_strength",
      "improvement_focus": "What this variation improves",
      "dalle_prompt": "Detailed DALL-E 3 prompt for a YouTube thumbnail (16:9, 1280x720). Professional YouTube thumbnail, ultra high quality. [specific visual description]..."
    }}
  ]
}}"""


@app.get("/blueprint/extract-thumb")
async def blueprint_extract_thumb(url: str = ""):
    """Extract thumbnail from YouTube URL and return base64 + URL."""
    if not url:
        return JSONResponse({"error": "YouTube URL required"}, status_code=400)
    video_id = extract_video_id(url)
    if not video_id:
        return JSONResponse({"error": "Could not parse YouTube video ID. Please check the URL."}, status_code=400)
    try:
        b64, thumb_url = await fetch_youtube_thumbnail_b64(video_id)
        return JSONResponse({
            "video_id":     video_id,
            "thumbnail_url": thumb_url,
            "image_b64":    b64,
        })
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        logger.error(f"/blueprint/extract-thumb error: {e}")
        return JSONResponse({"error": "Failed to fetch thumbnail."}, status_code=500)


@app.post("/blueprint/analyze")
async def blueprint_analyze(request: Request):
    """Analyze a YouTube thumbnail with GPT-4o Vision. 7-dimension scoring."""
    email      = request.headers.get("X-User-Email", "").strip().lower()
    admin_code = request.headers.get("X-Admin-Code", "").strip().upper()
    is_adm     = is_admin(admin_code)

    # Plan gating — free: 1/day via Redis fingerprint
    if not is_adm:
        if email:
            pd    = await get_user_plan(email)
            plan  = pd.get("plan", "free")
            used  = pd.get("blueprint_used", 0)
            limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).get("blueprint", 1)
            if used >= limit:
                return JSONResponse({"error": "upgrade_required", "plan": plan}, status_code=403)
        else:
            fp  = get_fingerprint(request)
            cnt = await redis_get(f"bp_free:{fp}")
            if cnt and int(cnt) >= 1:
                return JSONResponse({"error": "free_limit_reached"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    image_b64     = data.get("image_b64", "")
    niche         = str(data.get("niche", "tech")).strip()
    topic_context = str(data.get("topic_context", "")).strip()

    if not image_b64:
        return JSONResponse({"error": "image_b64 required"}, status_code=400)
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    try:
        import asyncio as _asyncio
        response = await _asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text",      "text": BLUEPRINT_SCORE_PROMPT.format(niche=niche)},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "low"}},
                    ]
                }],
                max_tokens=800,
                response_format={"type": "json_object"},
            ),
            timeout=25
        )
        result = parse_json_safe(response.choices[0].message.content)

        # Increment usage counters
        if not is_adm:
            if email:
                await sb_update_user(email, {"blueprint_used": used + 1})
                await invalidate_plan_cache(email)
            else:
                fp  = get_fingerprint(request)
                cnt = await redis_incr(f"bp_free:{fp}")
                if cnt == 1:
                    await redis_expire(f"bp_free:{fp}", 86400)  # 24h reset

        return JSONResponse(result)

    except Exception as e:
        logger.error(f"/blueprint/analyze error: {e}")
        return JSONResponse({"error": "Analysis failed. Please try again."}, status_code=500)


@app.post("/blueprint/variations")
async def blueprint_variations(request: Request):
    """Generate 3–5 DALL-E 3 improved thumbnail variations."""
    email      = request.headers.get("X-User-Email", "").strip().lower()
    admin_code = request.headers.get("X-Admin-Code", "").strip().upper()
    is_adm     = is_admin(admin_code)

    # Variations require at least Creator plan
    if not is_adm:
        if not email:
            return JSONResponse({"error": "upgrade_required"}, status_code=403)
        pd   = await get_user_plan(email)
        plan = pd.get("plan", "free")
        if plan == "free":
            return JSONResponse({"error": "upgrade_required", "plan": "free"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    scores          = data.get("scores", {})
    biggest_weakness = data.get("biggest_weakness", "text readability")
    niche           = str(data.get("niche", "tech")).strip()
    topic_context   = str(data.get("topic_context", "")).strip()

    # Number of variations by plan
    plan_data = await get_user_plan(email) if email else {"plan": "free"}
    plan      = plan_data.get("plan", "free") if not is_adm else "pro"
    count     = 3 if plan == "pro" else 2

    # Build scores summary string
    scores_summary = "\n".join(
        f"- {k.replace('_',' ').title()}: {v.get('score',0)}/100 ({v.get('label','')})"
        for k, v in scores.items()
    ) if scores else "Scores not available"

    try:
        # Step 1: Generate prompts via GPT-4o
        prompt_response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": BLUEPRINT_VARIATIONS_PROMPT.format(
                    count=count,
                    scores_summary=scores_summary,
                    biggest_weakness=biggest_weakness,
                    niche=niche,
                    topic_context=topic_context or "general content",
                )
            }],
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        prompts_data = parse_json_safe(prompt_response.choices[0].message.content)
        variations   = prompts_data.get("variations", [])[:count]

        if not variations:
            return JSONResponse({"error": "Could not generate variation prompts."}, status_code=500)

        # Step 2: Generate DALL-E images in parallel
        async def gen_image(v):
            try:
                dalle_prompt = v.get("dalle_prompt", "")
                # Enforce correct spelling via letter-by-letter technique for text overlays
                img_resp = await asyncio.wait_for(
                    client.images.generate(
                        model="dall-e-3",
                        prompt=dalle_prompt + " Style: professional YouTube thumbnail, photorealistic, 16:9 aspect ratio, high contrast, vibrant colors.",
                        size="1792x1024",
                        quality="standard",
                        n=1,
                    ),
                    timeout=25
                )
                return {
                    "variation_number":   v.get("variation_number", 1),
                    "targets":            v.get("targets", ""),
                    "improvement_focus":  v.get("improvement_focus", ""),
                    "image_url":          img_resp.data[0].url,
                }
            except Exception as e:
                logger.error(f"DALL-E variation error: {e}")
                return None

        results = await asyncio.gather(*[gen_image(v) for v in variations])
        results = [r for r in results if r is not None]

        return JSONResponse({"variations": results, "count": len(results)})

    except Exception as e:
        logger.error(f"/blueprint/variations error: {e}")
        return JSONResponse({"error": "Variation generation failed."}, status_code=500)

# ── Image Proxy (fixes CORS on DALL-E download) ───────────────────────────────
@app.get("/proxy-image")
async def proxy_image(url: str = ""):
    """Proxy OpenAI/DALL-E image URLs to allow canvas download without CORS issues."""
    ALLOWED = ["oaidalleapiprodscus.blob.core.windows.net", "openai.com", "blob.core.windows.net"]
    if not url or not any(d in url for d in ALLOWED):
        return JSONResponse({"error": "Invalid image URL"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=20.0) as h:
            r = await h.get(url, follow_redirects=True)
            from fastapi.responses import Response
            return Response(
                content=r.content,
                media_type=r.headers.get("content-type", "image/png"),
                headers={"Cache-Control": "public, max-age=3600",
                         "Access-Control-Allow-Origin": "*"}
            )
    except Exception as e:
        logger.error(f"/proxy-image error: {e}")
        return JSONResponse({"error": "Failed to fetch image"}, status_code=500)
# ═══════════════════════════════════════════════════════════════
# ENTERPRISE — API KEY + TEAM MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def generate_api_key(email: str) -> str:
    """Generate a deterministic but secure API key for enterprise user."""
    import hashlib, secrets
    base = hashlib.sha256(f"{email}:{secrets.token_hex(8)}".encode()).hexdigest()
    return f"tg-ent-{base[:32]}"

async def sb_get_team_members(owner_email: str):
    """Get all team members for an enterprise owner."""
    try:
        r = await _http_sb.get(
            f"{SUPABASE_URL}/rest/v1/users?team_owner_email=eq.{owner_email}&select=email,plan,images_used,thumb_analysis_used,created_at",
            headers=SB_HEADERS)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        logger.error(f"sb_get_team_members: {e}"); return []

async def send_team_invite_email(member_email: str, owner_email: str, login_token: str):
    """Send invite email to a new team member."""
    login_url = f"{APP_URL}/activate?login_token={login_token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post("https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={
                    "from": f"ThumbGenius <{FROM_EMAIL}>",
                    "to": [member_email],
                    "subject": "🏢 You've been invited to ThumbGenius Enterprise",
                    "html": f"""<div style="font-family:Arial;max-width:600px;margin:0 auto;background:#02020A;color:#fff;padding:40px;border-radius:12px;">
                        <h1 style="color:#43E97B">ThumbGenius Enterprise</h1>
                        <p style="color:#aaa">YouTube Packaging Intelligence Platform</p>
                        <h2>You've been invited! 🎉</h2>
                        <p style="color:#ccc"><strong>{owner_email}</strong> has invited you to their ThumbGenius Enterprise team.</p>
                        <a href="{login_url}" style="display:inline-block;background:#43E97B;color:#02020A;font-weight:bold;font-size:18px;padding:16px 40px;border-radius:8px;text-decoration:none;margin:24px 0;">Accept Invite & Login →</a>
                        <p style="color:#666;font-size:14px">This link expires in 24 hours.</p>
                        <p style="color:#444;font-size:12px">ThumbGenius · thumbgenius.in</p>
                    </div>"""
                })
        logger.info(f"Team invite sent to {member_email}")
    except Exception as e:
        logger.error(f"Team invite email error: {e}")

@app.get("/enterprise/api-key")
async def enterprise_get_api_key(request: Request):
    """Get or generate API key for enterprise user."""
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    user = await sb_get_user(email)
    if not user or user.get("plan") != "enterprise":
        return JSONResponse({"error": "Enterprise plan required"}, status_code=403)
    # Return existing key or generate new one
    api_key = user.get("api_key")
    if not api_key:
        api_key = generate_api_key(email)
        await sb_update_user(email, {"api_key": api_key})
    return JSONResponse({"api_key": api_key})

@app.post("/enterprise/regenerate-key")
async def enterprise_regenerate_api_key(request: Request):
    """Regenerate API key for enterprise user."""
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    user = await sb_get_user(email)
    if not user or user.get("plan") != "enterprise":
        return JSONResponse({"error": "Enterprise plan required"}, status_code=403)
    api_key = generate_api_key(email)
    await sb_update_user(email, {"api_key": api_key})
    return JSONResponse({"api_key": api_key})

@app.post("/enterprise/invite")
async def enterprise_invite_member(request: Request):
    """Invite a team member to enterprise account."""
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    owner = await sb_get_user(email)
    if not owner or owner.get("plan") != "enterprise":
        return JSONResponse({"error": "Enterprise plan required"}, status_code=403)
    # Check seat limit
    members = await sb_get_team_members(email)
    seat_limit = owner.get("seat_limit") or 5
    if len(members) >= seat_limit:
        return JSONResponse({"error": f"Seat limit reached ({seat_limit} seats). Contact support to add more."}, status_code=400)
    try:
        data = await request.json()
        member_email = data.get("email","").strip().lower()
    except:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    if not member_email or "@" not in member_email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    if member_email == email:
        return JSONResponse({"error": "Cannot invite yourself"}, status_code=400)
    # Create or update member account
    existing = await sb_get_user(member_email)
    import secrets as _sec
    from datetime import timezone as _tz
    login_token = _sec.token_urlsafe(32)
    token_expires = (datetime.now(_tz.utc) + timedelta(hours=24)).isoformat()
    if existing:
        await sb_update_user(member_email, {
            "plan": "enterprise",
            "team_owner_email": email,
            "login_token": login_token,
            "login_token_expires": token_expires
        })
    else:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post(f"{SUPABASE_URL}/rest/v1/users",
                headers={**SB_HEADERS, "Prefer": "return=minimal"},
                json={
                    "email": member_email,
                    "plan": "enterprise",
                    "team_owner_email": email,
                    "login_token": login_token,
                    "login_token_expires": token_expires
                })
    asyncio.create_task(send_team_invite_email(member_email, email, login_token))
    return JSONResponse({"success": True, "message": f"Invite sent to {member_email}"})

@app.get("/enterprise/team")
async def enterprise_get_team(request: Request):
    """Get team members list for enterprise owner."""
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    user = await sb_get_user(email)
    if not user or user.get("plan") != "enterprise":
        return JSONResponse({"error": "Enterprise plan required"}, status_code=403)
    members = await sb_get_team_members(email)
    return JSONResponse({
        "members": members,
        "seat_limit": user.get("seat_limit") or 5,
        "seats_used": len(members)
    })

@app.delete("/enterprise/remove-member")
async def enterprise_remove_member(request: Request):
    """Remove a team member from enterprise account."""
    email = request.headers.get("X-User-Email","").strip().lower()
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    owner = await sb_get_user(email)
    if not owner or owner.get("plan") != "enterprise":
        return JSONResponse({"error": "Enterprise plan required"}, status_code=403)
    try:
        data = await request.json()
        member_email = data.get("email","").strip().lower()
    except:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    await sb_update_user(member_email, {"plan": "free", "team_owner_email": None})
    return JSONResponse({"success": True})

# ═══════════════════════════════════════════════════════════════
# MAGIC LINK LOGIN — FOR ALL USERS
# ═══════════════════════════════════════════════════════════════

async def send_login_link_email(email: str, token: str):
    login_url = f"{APP_URL}/activate?login_token={token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post("https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={
                    "from": f"ThumbGenius <{FROM_EMAIL}>",
                    "to": [email],
                    "subject": "🔑 Your ThumbGenius Login Link",
                    "html": f"""<div style="font-family:Arial;max-width:600px;margin:0 auto;background:#02020A;color:#fff;padding:40px;border-radius:12px;">
                        <h1 style="color:#FDE036">ThumbGenius</h1>
                        <p style="color:#aaa">YouTube Packaging Intelligence Platform</p>
                        <h2>Your Login Link 🔑</h2>
                        <p style="color:#ccc">Click below to login. Link expires in 15 minutes.</p>
                        <a href="{login_url}" style="display:inline-block;background:#FDE036;color:#02020A;font-weight:bold;font-size:18px;padding:16px 40px;border-radius:8px;text-decoration:none;margin:24px 0;">Login to ThumbGenius →</a>
                        <p style="color:#666;font-size:14px">If you didn't request this, ignore this email.</p>
                        <p style="color:#444;font-size:12px">ThumbGenius · thumbgenius.in</p>
                    </div>"""
                })
        logger.info(f"Login link sent to {email}")
    except Exception as e:
        logger.error(f"Login link email error: {e}")

@app.post("/send-login-link")
async def send_login_link(request: Request):
    try:
        data = await request.json()
        email = data.get("email", "").strip().lower()
    except:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    # Get or create user
    user = await sb_get_user(email)
    from datetime import timezone as _tz
    token = secrets.token_urlsafe(32)
    token_expires = (datetime.now(_tz.utc) + timedelta(minutes=15)).isoformat()
    if user:
        await sb_update_user(email, {"login_token": token, "login_token_expires": token_expires})
    else:
        async with httpx.AsyncClient(timeout=10.0) as h:
            await h.post(f"{SUPABASE_URL}/rest/v1/users",
                headers={**SB_HEADERS, "Prefer": "return=minimal"},
                json={"email": email, "plan": "free", "login_token": token, "login_token_expires": token_expires})
    asyncio.create_task(send_login_link_email(email, token))
    return JSONResponse({"success": True, "message": "Login link sent! Check your email."})

