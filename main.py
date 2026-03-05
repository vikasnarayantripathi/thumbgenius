from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI
from dotenv import load_dotenv
from prompts import get_prompt
import os, json, time

load_dotenv()
app = FastAPI()
templates = Jinja2Templates(directory="templates")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Simple in-memory free tier tracking
free_uses = {}
image_uses = {}
MAX_FREE = 3
MAX_FREE_IMAGES = 1

def get_ip(request: Request):
    return request.client.host

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/generate")
async def generate(request: Request):
    ip = get_ip(request)
    data = await request.json()
    topic = data.get("topic", "").strip()
    niche = data.get("niche", "general").strip()
    if not topic:
        return JSONResponse({"error": "Please enter a video topic"}, status_code=400)
    uses = free_uses.get(ip, 0)
    if uses >= MAX_FREE:
        return JSONResponse({
            "error": "free_limit_reached",
            "message": "You've used all 3 free generations. Upgrade for unlimited access."
        }, status_code=403)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a YouTube growth expert. Always respond in valid JSON only."},
                {"role": "user", "content": get_prompt(topic, niche)}
            ],
            temperature=0.8
        )
        raw = response.choices[0].message.content
        raw = raw.strip().strip("```json").strip("```").strip()
        result = json.loads(raw)
        free_uses[ip] = uses + 1
        result["uses_remaining"] = MAX_FREE - (uses + 1)
        return JSONResponse(result)
    except json.JSONDecodeError:
        return JSONResponse({"error": "AI returned invalid response. Please try again."}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/generate-image")
async def generate_image(request: Request):
    ip = get_ip(request)
    data = await request.json()
    concept = data.get("concept", "").strip()
    text_overlay = data.get("text_overlay", "").strip()
    niche = data.get("niche", "general").strip()
    if not concept:
        return JSONResponse({"error": "No concept provided"}, status_code=400)
    img_uses = image_uses.get(ip, 0)
    if img_uses >= MAX_FREE_IMAGES:
        return JSONResponse({
            "error": "image_limit_reached",
            "message": "You've used your free image generation. Upgrade for more."
        }, status_code=403)
    try:
        image_prompt = f"""Professional YouTube thumbnail image.
Background: {concept}
Large bold text overlay saying: {text_overlay}
Style: Ultra high contrast, vibrant colors, professional YouTube thumbnail.
The text must be very large, bold and clearly readable.
Make it extremely eye-catching and click-worthy.
16:9 aspect ratio. No watermarks. No borders."""
        response = client.images.generate(
            model="dall-e-3",
            prompt=image_prompt,
            size="1792x1024",
            quality="standard",
            n=1
        )
        image_url = response.data[0].url
        image_uses[ip] = img_uses + 1
        return JSONResponse({
            "image_url": image_url,
            "images_remaining": MAX_FREE_IMAGES - (img_uses + 1)
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/ab-test")
async def ab_test(request: Request):
    data = await request.json()
    title_a = data.get("titleA", "").strip()
    title_b = data.get("titleB", "").strip()
    if not title_a or not title_b:
        return JSONResponse({"error": "Missing titles"}, status_code=400)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a YouTube CTR expert. Always respond in valid JSON only."},
                {"role": "user", "content": "Compare these two YouTube titles for Indian audience. Title A: " + title_a + " --- Title B: " + title_b + " --- Respond ONLY in this exact JSON format with no markdown: {\"winner\":\"A or B\",\"score_a\":8,\"score_b\":7,\"reasoning\":\"2-3 sentences on which gets more clicks and why\"}"}
            ],
            temperature=0.7
        )
        raw = response.choices[0].message.content.strip().strip("```json").strip("```").strip()
        return JSONResponse(json.loads(raw))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/analyze-channel")
async def analyze_channel(request: Request):
    data = await request.json()
    titles = data.get("titles", "").strip()
    if not titles:
        return JSONResponse({"error": "Missing titles"}, status_code=400)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a YouTube growth expert. Always respond in valid JSON only."},
                {"role": "user", "content": "Analyze these Indian YouTube video titles: " + titles + " --- Respond ONLY in this exact JSON format with no markdown: {\"ctr_score\":7,\"emotion_score\":6,\"clarity_score\":8,\"issues\":[{\"title\":\"issue name\",\"detail\":\"explanation\"}],\"fixes\":[{\"title\":\"fix name\",\"detail\":\"how to apply\"}],\"rewrites\":[{\"original\":\"old title\",\"improved\":\"better title\"}]}"}
            ],
            temperature=0.7
        )
        raw = response.choices[0].message.content.strip().strip("```json").strip("```").strip()
        return JSONResponse(json.loads(raw))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

trending_cache = {"data": None, "generated_at": 0}

@app.get("/trending")
async def trending():
    now = time.time()
    if trending_cache["data"] and now - trending_cache["generated_at"] < 21600:
        return JSONResponse(trending_cache["data"])
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a YouTube trends expert. Always respond in valid JSON only."},
                {"role": "user", "content": "Generate 16 trending YouTube video topics for Indian creators in 2025. Return ONLY a JSON array with no markdown: [{\"niche\":\"tech\",\"topic\":\"video idea\",\"why\":\"why trending in India\",\"heat\":\"fire emoji\"}] Cover these niches (2 topics each): tech, finance, gaming, fitness, cricket, automobiles, examprep, motivation"}
            ],
            temperature=0.9
        )
        raw = response.choices[0].message.content.strip().strip("```json").strip("```").strip()
        result = json.loads(raw)
        trending_cache["data"] = result
        trending_cache["generated_at"] = now
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/health")
async def health():
    return {"status": "ok"}