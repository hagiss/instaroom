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
│       ├── models.py                  # Pydantic models for inter-stage data flow
│       ├── gemini_client.py           # Shared Gemini client singleton + image utilities
│       ├── pipeline.py                # Orchestrator: runs Stages 1-4, saves debug output
│       ├── crawler/scraper.py         # Stage 0: Apify Instagram Scraper
│       ├── vlm/
│       │   ├── analysis.py            # Stage 1: Per-post VLM analysis
│       │   ├── aggregation.py         # Stage 2: Persona profile aggregation
│       │   └── prompt.py              # Stage 3: Agentic prompt design
│       ├── image_gen/generate.py      # Stage 4: Image gen + self-critique
│       └── worldslabs/convert.py      # Stage 5: World Labs 3D conversion
├── pyproject.toml
└── .env.example

frontend/                              # Next.js + Spark (Three.js) for 3D rendering
```

## Pipeline

```
Username ─► Stage 0 ─► Stage 1 ─► Stage 2 ─► Stage 3 ─► Stage 4 ─► Stage 5 ─► 3D Room
            Crawl       Analyze    Aggregate   Prompt     Image Gen   3D Convert
            (Apify      (Gemini    (Gemini     (Gemini    (Image Gen  (World Labs
             Scraper)    Flash)     Flash)      Flash)     Model)      Marble)
```

### Stage 0 — Data Collection (`services/crawler/scraper.py`)

- Calls the `apify/instagram-scraper` actor via Apify API to fetch profile metadata and the 10 most recent posts
- Requires `APIFY_API_TOKEN` — no Instagram login needed
- Fallback: direct photo upload (5–10 images + optional bio)
- Returns: list of `Post` objects (images, caption, hashtags, likes, date, location)

### Stage 1 — Per-Post Analysis (`services/vlm/analysis.py`)

- Sends each post (image + caption + hashtags) to **Gemini Flash**
- Analyzes ALL post types including videos (uses thumbnail image)
- For carousel posts: sends ALL images in one VLM call for holistic analysis
- Extracts structured JSON per post: objects, scene, people, emotional_weight, frame_worthy
- Concurrent analysis with `asyncio.gather` + semaphore for rate limiting

### Stage 2 — Aggregation (`services/vlm/aggregation.py`)

- Combines all per-post analyses into a single persona profile
- **VLM-based semantic deduplication**: groups similar objects (e.g., "acoustic_guitar"/"guitar" → "guitar")
- Object importance scoring: `f(frequency, prominence, emotional_weight, likes)` → top 8 objects
- Tracks `source_image_url` for each object (the post where it appears most prominently)
- Room atmosphere derivation: dominant mood, lighting, color palette, style, window view
- **VLM persona synthesis**: generates persona summary and refines atmosphere
- Total: 2 VLM calls (dedup + synthesis)

### Stage 3 — Prompt Design (`services/vlm/prompt.py`)

- Takes the aggregated profile and builds an image generation prompt step by step via Gemini Flash
- Generates a **single-viewpoint** prompt — describes what's visible from one camera angle
- Hard constraint: the chosen viewpoint MUST have ALL important objects visible in frame
- Sub-steps (3 VLM calls): layout planning → object detail descriptions → final prompt assembly
- **Reference image strategy**: passes source images for key objects so the generator can reproduce their actual appearance (e.g., the specific guitar, the specific cat)
- Final prompt references images by number: "the guitar from reference image 1"

### Stage 4 — Image Generation + Critique (`services/image_gen/generate.py`)

- Calls image generation model with the assembled prompt + reference images (up to 14)
- Self-critique via Gemini Flash: scores object_presence, atmosphere_match, spatial_coherence, overall_quality (each 1–4)
- **1 round max**: generate → critique → optionally regenerate once if avg score < 3.5
- Returns best attempt by average critique score

### Stage 5 — 3D Conversion (`services/worldslabs/convert.py`)

- Sends the final room image to **World Labs API** (Marble 0.1-plus or 0.1-mini)
- Output: Gaussian splat + collider mesh + thumbnail + panorama
- Rendered in browser via Spark (Three.js-based)

### Debug Output

The pipeline orchestrator (`services/pipeline.py`) saves all intermediate results to `output/{username}_{timestamp}.json`:
- Stage 1: Full per-post analyses
- Stage 2: Aggregated profile (persona, objects, atmosphere)
- Stage 3: Layout plan, object details, final prompt, reference image mapping
- Stage 4: Critique scores per attempt (images saved as separate PNG files)

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
| Image Gen | Gemini image generation model |
| 3D Gen | World Labs Marble API |
| 3D Rendering | Spark (Three.js) |
| Frontend | Next.js |
| Hosting | Vercel (frontend) + Render (backend) |

## Environment Variables

```
GOOGLE_API_KEY=         # Gemini Flash + image generation
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
