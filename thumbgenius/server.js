/**
 * ThumbGenius — server.js
 * Run: node server.js
 * Env vars required:
 *   ANTHROPIC_API_KEY   — your Anthropic key
 *   OPENAI_API_KEY      — your OpenAI key (for DALL-E image generation)
 *   PORT                — optional, defaults to 3000
 */

const express = require('express');
const path = require('path');
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const PORT = process.env.PORT || 3000;

// Simple in-memory rate limiting per IP
// Tracks: { ip: { uses, imageUses, lastReset } }
const usageStore = {};
const FREE_LIMIT = 3;
const FREE_IMAGE_LIMIT = 1;
const RESET_HOURS = 24;

function getUsage(ip) {
    const now = Date.now();
    if (!usageStore[ip] || now - usageStore[ip].lastReset > RESET_HOURS * 3600 * 1000) {
        usageStore[ip] = { uses: 0, imageUses: 0, lastReset: now };
    }
    return usageStore[ip];
}

// ─── Anthropic helper ────────────────────────────────────────────────────────
async function callClaude(prompt, maxTokens = 1500) {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01'
        },
        body: JSON.stringify({
            model: 'claude-sonnet-4-20250514',
            max_tokens: maxTokens,
            messages: [{ role: 'user', content: prompt }]
        })
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error.message || 'Claude API error');
    const text = data.content[0].text.replace(/```json|```/g, '').trim();
    return JSON.parse(text);
}

// ─── ROUTE: Generate content package ────────────────────────────────────────
app.post('/generate', async (req, res) => {
    const ip = req.ip || req.connection.remoteAddress;
    const usage = getUsage(ip);

    if (usage.uses >= FREE_LIMIT) {
        return res.json({ error: 'free_limit_reached' });
    }

    const { topic, niche } = req.body;
    if (!topic || !niche) return res.status(400).json({ error: 'Missing topic or niche' });

    try {
        const result = await callClaude(`You are a YouTube growth expert specialising in Indian creators. Generate a complete content package for this video topic.
Topic: "${topic}"
Niche: "${niche}"

Respond ONLY in valid JSON with no markdown:
{
  "titles": ["title1","title2","title3","title4","title5"],
  "thumbnail": {
    "background": "describe the background scene",
    "face_expression": "describe creator face expression",
    "text_overlay": "SHORT PUNCHY TEXT (max 4 words)",
    "emotion_trigger": "curiosity/shock/fear/excitement",
    "ctr_score": 8.5,
    "why_it_works": "2-sentence explanation"
  },
  "hook_script": "Write the first 15 seconds of the video hook as a spoken script",
  "niche_tip": "One specific insight about what makes videos in this niche go viral in India"
}`, 2000);

        usage.uses++;
        result.uses_remaining = FREE_LIMIT - usage.uses;
        res.json(result);
    } catch (e) {
        console.error('/generate error:', e.message);
        res.status(500).json({ error: 'Generation failed. Please try again.' });
    }
});

// ─── ROUTE: Generate thumbnail image (DALL-E 3) ──────────────────────────────
app.post('/generate-image', async (req, res) => {
    const ip = req.ip || req.connection.remoteAddress;
    const usage = getUsage(ip);

    if (usage.imageUses >= FREE_IMAGE_LIMIT) {
        return res.json({ error: 'image_limit_reached' });
    }

    const { concept, textOverlay } = req.body;
    if (!concept) return res.status(400).json({ error: 'Missing concept' });

    try {
        const prompt = `YouTube thumbnail image. ${concept}. Bold text overlay saying "${textOverlay || ''}". High contrast, vibrant colors, professional YouTube thumbnail style, 16:9 aspect ratio, eye-catching, clickbait style but tasteful.`;

        const imgRes = await fetch('https://api.openai.com/v1/images/generations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${OPENAI_API_KEY}`
            },
            body: JSON.stringify({
                model: 'dall-e-3',
                prompt,
                n: 1,
                size: '1792x1024',
                quality: 'standard'
            })
        });

        const imgData = await imgRes.json();
        if (imgData.error) throw new Error(imgData.error.message);

        usage.imageUses++;
        res.json({
            image_url: imgData.data[0].url,
            images_remaining: FREE_IMAGE_LIMIT - usage.imageUses
        });
    } catch (e) {
        console.error('/generate-image error:', e.message);
        res.status(500).json({ error: 'Image generation failed. Please try again.' });
    }
});

// ─── ROUTE: A/B Title Tester ─────────────────────────────────────────────────
app.post('/ab-test', async (req, res) => {
    const { titleA, titleB } = req.body;
    if (!titleA || !titleB) return res.status(400).json({ error: 'Missing titles' });

    try {
        const result = await callClaude(`You are a YouTube CTR expert. Compare these two video titles and respond ONLY in valid JSON with no markdown:
Title A: "${titleA}"
Title B: "${titleB}"
Return: {"winner":"A or B","score_a":number_1_to_10,"score_b":number_1_to_10,"reasoning":"2-3 sentences explaining which title will get more clicks and why, focusing on curiosity, emotion, and clarity"}`, 1000);

        res.json(result);
    } catch (e) {
        console.error('/ab-test error:', e.message);
        res.status(500).json({ error: 'Test failed. Please try again.' });
    }
});

// ─── ROUTE: Channel Analyzer ─────────────────────────────────────────────────
app.post('/analyze-channel', async (req, res) => {
    const { titles } = req.body;
    if (!titles) return res.status(400).json({ error: 'Missing titles' });

    try {
        const result = await callClaude(`You are a YouTube growth expert. Analyze these video titles from an Indian YouTube creator and respond ONLY in valid JSON with no markdown:
Titles: "${titles}"
Return: {
  "ctr_score": number_1_to_10,
  "emotion_score": number_1_to_10,
  "clarity_score": number_1_to_10,
  "issues": [{"title":"Issue name","detail":"explanation"}],
  "fixes": [{"title":"Fix name","detail":"how to apply it"}],
  "rewrites": [{"original":"original title","improved":"better version"}]
}`, 1500);

        res.json(result);
    } catch (e) {
        console.error('/analyze-channel error:', e.message);
        res.status(500).json({ error: 'Analysis failed. Please try again.' });
    }
});

// ─── ROUTE: Trending Topics ───────────────────────────────────────────────────
// Cache trending for 6 hours to save API calls
let trendingCache = { data: null, generatedAt: 0 };
const TRENDING_TTL_MS = 6 * 3600 * 1000;

app.get('/trending', async (req, res) => {
    const now = Date.now();
    if (trendingCache.data && now - trendingCache.generatedAt < TRENDING_TTL_MS) {
        return res.json(trendingCache.data);
    }

    try {
        const result = await callClaude(`Generate 16 trending YouTube video topics for Indian creators right now in 2025. Mix of niches. Respond ONLY in valid JSON array with no markdown:
[{"niche":"tech","topic":"video topic idea","why":"why this is trending now in India","heat":"🔥🔥🔥 or 🔥🔥 or 🔥"}]
Niches to cover: tech, finance, gaming, fitness, cricket, automobiles, examprep, motivation (2 each)`, 2000);

        trendingCache = { data: result, generatedAt: now };
        res.json(result);
    } catch (e) {
        console.error('/trending error:', e.message);
        res.status(500).json({ error: 'Failed to load trending topics.' });
    }
});

// ─── Serve index ──────────────────────────────────────────────────────────────
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
    console.log(`ThumbGenius running on http://localhost:${PORT}`);
});
