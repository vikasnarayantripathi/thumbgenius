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
free_uses = {}  # {ip: count}
MAX_FREE = 3

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

    # Check free tier limit
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
        # Clean JSON if wrapped in backticks
        raw = raw.strip().strip("```json").strip("```").strip()
        result = json.loads(raw)

        # Increment free use counter
        free_uses[ip] = uses + 1
        result["uses_remaining"] = MAX_FREE - (uses + 1)

        return JSONResponse(result)

    except json.JSONDecodeError:
        return JSONResponse({"error": "AI returned invalid response. Please try again."}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/health")
async def health():
    return {"status": "ok"}