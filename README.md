# Instaroom

Analyze an Instagram profile and generate a personalized, explorable 3D room that represents who that person is.

## Architecture

```
backend/
├── app/
│   ├── main.py                        # FastAPI app, router registration
│   ├── routes/
│   │   └── generate.py                # POST /generate — orchestrates the full pipeline
│   └── services/
│       ├── crawler/scraper.py         # Stage 0: Instaloader wrapper
│       ├── vlm/
│       │   ├── analysis.py            # Stage 1: Per-post VLM analysis
│       │   ├── aggregation.py         # Stage 2: Persona profile aggregation
│       │   └── prompt.py              # Stage 3: Agentic prompt design
│       ├── image_gen/generate.py      # Stage 4: Nano Banana Pro + self-critique
│       └── worldslabs/convert.py      # Stage 5: World Labs 3D conversion
├── pyproject.toml
└── .env.example

frontend/                              # Next.js + Spark (Three.js) for 3D rendering
```

## Pipeline

```
Username ─► Stage 0 ─► Stage 1 ─► Stage 2 ─► Stage 3 ─► Stage 4 ─► Stage 5 ─► 3D Room
            Crawl       Analyze    Aggregate   Prompt     Image Gen   3D Convert
            (Insta-     (Gemini    (Gemini     (Gemini    (Nano       (World Labs
             loader)     Flash)     Flash)      Flash)     Banana)     Marble)
```

### Stage 0 — Data Collection (`services/crawler/scraper.py`)

- Wraps Instaloader to fetch profile metadata and recent posts (50–100)
- Requires an Instagram session cookie (`INSTAGRAM_SESSION_ID`)
- Fallback: direct photo upload (5–10 images + optional bio)
- Returns: list of `Post` objects (images, caption, hashtags, likes, date, location)

### Stage 1 — Per-Post Analysis (`services/vlm/analysis.py`)

- Sends each post (image + caption + hashtags) to **Gemini Flash**
- Extracts structured JSON per post: objects, scene, people, emotional_weight, frame_worthy
- All posts are analyzed independently — can be parallelized with `asyncio.gather`

### Stage 2 — Aggregation (`services/vlm/aggregation.py`)

- Combines all per-post analyses into a single persona profile
- Object importance scoring: `f(frequency, prominence, emotional_weight, likes)` → top 5–8 objects
- Frame photo selection: rank frame_worthy posts by emotional_weight + likes → 3–5 photos
- Room atmosphere derivation: dominant mood, lighting, color palette, style, window view

### Stage 3 — Prompt Design (`services/vlm/prompt.py`)

- Takes the aggregated profile and builds a Nano Banana Pro prompt step by step via Gemini Flash
- Sub-steps: layout planning → object detail descriptions → frame photo descriptions → final assembly
- Also selects reference images (frame source photos + atmosphere reference) for the image gen call

### Stage 4 — Image Generation + Critique (`services/image_gen/generate.py`)

- Calls **Nano Banana Pro** (Gemini Pro Image Preview) with the assembled prompt + reference images
- Self-critique via Gemini Flash: scores object_presence, atmosphere_match, spatial_coherence, frame_photos, overall_quality (each 1–5)
- Retries up to 3 times, adjusting the prompt based on low-scoring criteria

### Stage 5 — 3D Conversion (`services/worldslabs/convert.py`)

- Sends the final room image to **World Labs API** (Marble 0.1-plus or 0.1-mini)
- Output: Gaussian splat + collider mesh + thumbnail + panorama
- Rendered in browser via Spark (Three.js-based)

## API

### `POST /generate`

Orchestrates the full pipeline. Called from the frontend.

Request:
```json
{"username": "instagram_handle"}
```

Response (on completion):
```json
{
  "room_url": "https://instaroom.xyz/username",
  "screenshot_url": "...",
  "persona_summary": "A person who loves nature and music..."
}
```

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI |
| Crawling | Instaloader |
| VLM / LLM | Gemini Flash (analysis, aggregation, prompt design, critique) |
| Image Gen | Nano Banana Pro (Gemini Pro Image Preview) |
| 3D Gen | World Labs Marble API |
| 3D Rendering | Spark (Three.js) |
| Frontend | Next.js |
| Hosting | Vercel (frontend) + Railway or Fly.io (backend) |

## Environment Variables

```
GOOGLE_API_KEY=         # Gemini Flash + Nano Banana Pro
INSTAGRAM_SESSION_ID=   # Instaloader session
WORLDLABS_API_KEY=      # World Labs Marble API
```

## Running Locally

```bash
# Backend
cd backend
pip install -e .
uvicorn app.main:app --reload

# Frontend (after Next.js init)
cd frontend
npm run dev
```
