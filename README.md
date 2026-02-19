# Instaroom

Analyze an Instagram profile and generate a personalized, explorable 3D room that represents who that person is.

## Architecture

```
backend/
├── app/
│   ├── main.py                        # FastAPI app, router registration
│   ├── routes/
│   │   ├── generate.py                # POST /api/generate, POST /api/generate/upload, GET /api/jobs/{id}
│   │   └── rooms.py                   # GET /api/rooms/{id}, GET /api/rooms/by-username/{username}
│   └── services/
│       ├── crawler/scraper.py         # Stage 0: Apify Instagram Scraper
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
            (Apify      (Gemini    (Gemini     (Gemini    (Nano       (World Labs
             Scraper)    Flash)     Flash)      Flash)     Banana)     Marble)
```

### Stage 0 — Data Collection (`services/crawler/scraper.py`)

- Calls the `apify/instagram-scraper` actor via Apify API to fetch profile metadata and the 10 most recent posts
- Requires `APIFY_API_TOKEN` — no Instagram login needed
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

Base URL: `/api`

### `POST /api/generate` — Start generation from Instagram username

Request:
```json
{
  "username": "instagram_handle"
}
```

Response `202 Accepted` (new job):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "existing": false
}
```

Deduplication — if a job or room already exists for this username:

| State | Response |
|---|---|
| No existing job | `202` — creates new job |
| Job in-progress for this username | `200` — returns existing `job_id`, `"existing": true` |
| Room already completed for this username | `200` — returns `job_id` + `room_id`, `"existing": true` |

### `POST /api/generate/upload` — Start generation from uploaded photos

Request: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `photos` | File[] | yes | 5–10 image files |
| `bio` | string | no | Optional bio / description text |

Response `202 Accepted`:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### `GET /api/jobs/{job_id}` — Poll job status

Response `200 OK`:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "instagram_handle",
  "status": "analyzing",
  "stage": 1,
  "progress": "Analyzing post 3/10",
  "result": null,
  "error": null
}
```

`status` values and corresponding `stage`:

| status | stage | Description |
|---|---|---|
| `crawling` | 0 | Fetching Instagram data via Apify |
| `analyzing` | 1 | Running per-post VLM analysis |
| `aggregating` | 2 | Building persona profile |
| `prompting` | 3 | Designing image generation prompt |
| `generating_image` | 4 | Generating room image + critique loop |
| `converting_3d` | 5 | Converting to 3D via World Labs |
| `completed` | — | Done, `result` is populated |
| `failed` | — | Error, `error` is populated |

On `completed`, `result` is:
```json
{
  "room_id": "abc123",
  "room_url": "https://instaroom.xyz/r/abc123",
  "screenshot_url": "https://cdn.instaroom.xyz/rooms/abc123/screenshot.png",
  "persona_summary": "A person who loves nature and music...",
  "viewer_data": {
    "splat_url": "https://cdn.instaroom.xyz/rooms/abc123/scene.splat",
    "collider_url": "https://cdn.instaroom.xyz/rooms/abc123/collider.glb",
    "panorama_url": "https://cdn.instaroom.xyz/rooms/abc123/panorama.png",
    "camera_position": [0.0, 1.5, 3.0],
    "camera_target": [0.0, 1.0, 0.0]
  }
}
```

On `failed`, `error` is:
```json
{
  "message": "Apify scraper timed out",
  "stage": 0
}
```

### `GET /api/rooms/{room_id}` — Get room data by room ID

Response `200 OK`:
```json
{
  "room_id": "abc123",
  "username": "instagram_handle",
  "persona_summary": "A person who loves nature and music...",
  "screenshot_url": "https://cdn.instaroom.xyz/rooms/abc123/screenshot.png",
  "viewer_data": {
    "splat_url": "https://cdn.instaroom.xyz/rooms/abc123/scene.splat",
    "collider_url": "https://cdn.instaroom.xyz/rooms/abc123/collider.glb",
    "panorama_url": "https://cdn.instaroom.xyz/rooms/abc123/panorama.png",
    "camera_position": [0.0, 1.5, 3.0],
    "camera_target": [0.0, 1.0, 0.0]
  }
}
```

Response `404 Not Found`:
```json
{
  "detail": "Room not found"
}
```

### `GET /api/rooms/by-username/{username}` — Get room data by Instagram username

Same response shape as `GET /api/rooms/{room_id}`.
Used for shareable links like `instaroom.xyz/r/johndoe`.

Response `404 Not Found` if no completed room exists for this username.
```

### `GET /health` — Health check

Response `200 OK`:
```json
{
  "status": "ok"
}
```

## Frontend Flow

```
Homepage (/):
  User enters username → POST /api/generate → get job_id
  Navigate to /status/{job_id}
  Store job_id in localStorage

Status page (/status/{job_id}):
  Poll GET /api/jobs/{job_id} every 3s
  Show progress bar with stage info
  On completed → redirect to /r/{username}
  User can leave and return — URL has job_id, polling resumes

Room page (/r/{username}):
  GET /api/rooms/by-username/{username}
  Load 3D viewer with viewer_data (splat, collider, camera)
  Shareable URL — this is what gets posted on social media

Returning user (homepage):
  Check localStorage for recent job_ids
  Show "Your room is still generating" or "View your room" banner
```

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI |
| Crawling | Apify Instagram Scraper |
| VLM / LLM | Gemini Flash (analysis, aggregation, prompt design, critique) |
| Image Gen | Nano Banana Pro (Gemini Pro Image Preview) |
| 3D Gen | World Labs Marble API |
| 3D Rendering | Spark (Three.js) |
| Frontend | Next.js |
| Hosting | Vercel (frontend) + Render (backend) |

## Environment Variables

```
GOOGLE_API_KEY=         # Gemini Flash + Nano Banana Pro
APIFY_API_TOKEN=        # Apify Instagram Scraper
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
