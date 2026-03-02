from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI
from dotenv import load_dotenv
from prompts import get_prompt
import os, json

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Simple in-memory free tier tracking
free_uses = {}      # {ip: count}
image_uses = {}     # {ip: count}
MAX_FREE = 3
MAX_FREE_IMAGES = 1  # 1 free image generation

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

@app.get("/health")
async def health():
    return {"status": "ok"}