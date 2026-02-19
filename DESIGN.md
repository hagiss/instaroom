# Insta Room — Design Document v2

> Analyze an Instagram profile and generate a personalized, explorable 3D room that represents who that person is.

---

## Pipeline Overview

```
[Input] → [Stage 0: Collection] → [Stage 1: Per-Post Analysis] → [Stage 2: Aggregation] → [Stage 3: Prompt Design] → [Stage 4: Image Generation + Critique] → [Stage 5: 3D Conversion] → [Output]
```

---

## Stage 0: Input & Data Collection

### 0-1. Public Accounts
- User enters Instagram username
- Server-side crawl via Instaloader (requires session login)
- Target: most recent 50–100 posts

### 0-2. Private Accounts / No Instagram
- User uploads 5–10 photos directly + optional bio text

### Per-Post Data Schema

| Field | Description |
|---|---|
| `image_urls` | Post image URLs (including carousel) |
| `video_url` | Video URL if applicable (+ thumbnail) |
| `caption` | Caption text |
| `hashtags` | Hashtag list |
| `likes` | Like count |
| `date` | Post date |
| `location` | Location tag (if present) |
| `is_video` | Whether post is a video |

### Profile Data Schema

| Field | Description |
|---|---|
| `biography` | Bio text |
| `profile_pic_url` | Profile picture URL |
| `follower_count` | Follower count |
| `post_count` | Total post count |

---

## Stage 1: Per-Post Analysis

**Model: Gemini 3 Flash**

Each post is analyzed individually by the VLM to produce structured JSON.

### 1-1. VLM Prompt (per post)

Input: image(s) + caption + hashtags
Output: structured JSON

```
Analyze this Instagram post and extract the following:

1. objects: List of notable objects/items visible in the image
   - name: object name (e.g., guitar, cat, film camera)
   - prominence: how central it is in the image (center / background / minor)
   - description: brief description (color, features, distinguishing traits)

2. scene: Scene information
   - location_type: indoor / outdoor / cafe / nature / city / beach / etc.
   - mood: atmosphere keywords (warm / cool / cozy / energetic / calm / ...)
   - lighting: lighting condition (natural / golden_hour / artificial / dark / bright)
   - color_palette: dominant 3–5 colors (hex codes or names)

3. people: People information
   - count: number of people
   - is_selfie: whether it's a selfie
   - activity: what they're doing (eating / traveling / working / hanging_out / ...)

4. emotional_weight: How personally meaningful this post appears to be (1–5)
   - Consider emotional depth of caption, whether it captures a special moment, etc.

5. frame_worthy: Would this image look good as a framed photo on a wall? (yes / no)
   - If yes, explain why (beautiful scenery, meaningful moment, artistic quality, etc.)
```

### 1-2. Example Output

```json
{
  "post_id": "abc123",
  "objects": [
    {"name": "acoustic_guitar", "prominence": "center", "description": "natural wood color, classical style"},
    {"name": "coffee_cup", "prominence": "background", "description": "white ceramic mug"}
  ],
  "scene": {
    "location_type": "cafe_indoor",
    "mood": ["warm", "cozy"],
    "lighting": "natural",
    "color_palette": ["#D4A574", "#8B6914", "#F5F0E8"]
  },
  "people": {"count": 0, "is_selfie": false, "activity": null},
  "emotional_weight": 3,
  "frame_worthy": true,
  "frame_reason": "aesthetic composition, warm tones, personal item (guitar)"
}
```

---

## Stage 2: Aggregation

**Model: Gemini 3 Flash**

Combine all per-post analyses into a unified persona profile.

### 2-1. Object Importance Scoring

Final importance score per object = f(frequency, prominence, emotional_weight, likes)

```
importance_score = (
    frequency × 0.3
  + avg_prominence × 0.25       # center=1.0, background=0.5, minor=0.2
  + avg_emotional_weight × 0.25
  + normalized_likes × 0.2
)
```

→ Select top 5–8 objects = **items to place in the room**

### 2-2. Frame Photo Selection

From posts where `frame_worthy=true`:
- Rank by emotional_weight (primary) and likes (secondary)
- Ensure scene diversity (landscape, people, food, etc. — avoid duplicates)

→ Select 3–5 photos = **framed pictures on the walls**

### 2-3. Room Atmosphere

Aggregate all scene data across posts:

```json
{
  "dominant_mood": "warm_cozy",
  "dominant_lighting": "natural",
  "color_palette": ["#D4A574", ...],
  "style": "vintage_minimal",
  "window_view": "ocean",
  "room_size": "medium",
  "time_of_day": "afternoon"
}
```

- `dominant_mood`: most frequent mood keywords
- `style`: inferred from mood + color palette
- `window_view`: derived from most frequent location_type (e.g., lots of beach photos → ocean view)
- `time_of_day`: derived from dominant lighting

### 2-4. Final Aggregated Profile

```json
{
  "persona_summary": "A person who loves nature and music. Spends time in cafes, enjoys shooting landscapes with a film camera. Prefers warm, cozy atmospheres.",
  "key_objects": [
    {"name": "acoustic_guitar", "importance": 0.92, "description": "..."},
    {"name": "film_camera", "importance": 0.85, "description": "..."},
    {"name": "cat", "importance": 0.78, "description": "orange tabby"}
  ],
  "frame_photos": [
    {"post_id": "abc", "description": "Jeju ocean sunset", "original_url": "..."},
    {"post_id": "def", "description": "Forest trail", "original_url": "..."}
  ],
  "atmosphere": { ... },
  "hashtag_themes": ["coffee", "travel", "film_photography", "cats"]
}
```

---

## Stage 3: Agentic Prompt Design

**Model: Gemini 3 Flash**

PaperBanana-style: build the image generation prompt step by step, not all at once.

### 3-1. Layout Planning

Feed the aggregated profile to LLM and ask it to plan spatial layout as text:

```
Given this person's profile, plan a room layout:
- Room shape (square / rectangular / L-shaped)
- Window placement and size (view outside: {window_view})
- Major furniture placement (bed / sofa / desk / etc.)
- Object placement (where each key_object goes)
- Frame placement (which wall, how many)
- Visual flow: what a visitor sees first when entering
```

### 3-2. Object Detail Descriptions

For each key_object, generate a detailed description in the room context:

```
Describe how this item naturally exists in the room:
- acoustic_guitar: wall-mounted, on a stand, or leaning against the sofa?
- Include color, material, how it harmonizes with the surrounding decor.
```

### 3-3. Frame Photo Descriptions

Generate descriptions for Nano Banana Pro to render original Instagram photos as in-room framed artwork:

```
Reinterpret this photo as a framed picture hanging on a room wall:
- Original: Jeju ocean sunset photo
- Frame style: matching {atmosphere.style}
- Slight artistic reinterpretation is okay (photo → painting feel, etc.)
```

### 3-4. Final Nano Banana Pro Prompt Assembly

Combine 3-1, 3-2, 3-3 into a single image generation prompt:

```
A medium-sized room bathed in warm afternoon natural light.
A large window on the left reveals an ocean view.
Walls are warm ivory, floor is natural wood.

[Furniture]
- Beige fabric sofa on the right
- Small wooden coffee table in front, with a white ceramic mug on top
- Small desk by the left window, with a vintage silver film camera on it

[Objects]
- Acoustic guitar wall-mounted next to the sofa
- Orange tabby cat curled up sleeping on the sofa
- Two small potted plants on the desk shelf

[Wall Frames]
- Three frames above the sofa:
  1) Ocean sunset landscape (warm orange/pink tones)
  2) Forest trail (green/brown tones)
  3) Cafe window scene (warm tones)

[Lighting / Atmosphere]
- 3–4 PM natural light streaming through the window
- Overall warm, cozy, lived-in feel
- Vintage minimal style
```

### 3-5. Reference Images

Nano Banana Pro supports reference images alongside the text prompt. Include:
- **Frame source photos**: The original Instagram photos selected as frame_worthy (so the model can reproduce their content inside the wall frames)
- **Atmosphere reference**: The single most representative Instagram photo (for overall color/tone/mood matching)
- **Style reference** (optional): A Pinterest/stock image of a room in the target style (e.g., "vintage minimal room") if the model struggles with style consistency

These are passed as `reference_images` in the Nano Banana Pro API call alongside the text prompt.

---

## Stage 4: Image Generation + Self-Critique

### 4-1. Generate Room Image

- **Model**: Nano Banana Pro (Gemini 3 Pro Image Preview)
- **Input**: Stage 3 final prompt + reference images (frame source photos + atmosphere reference)
- **Output**: A single room image representing the person

### 4-2. Self-Critique via VLM

**Model: Gemini 3 Flash**

Feed the generated image back to VLM for evaluation:

```
Compare the following:

A. Original intent (prompt summary):
   - Objects: guitar, film camera, cat, coffee cup, plants
   - Frames: ocean sunset, forest trail, cafe window
   - Atmosphere: warm, cozy, vintage minimal, natural light

B. Generated image

Score each (1–5) with improvement suggestions:
1. object_presence: Are all requested objects present? Which are missing?
2. atmosphere_match: Does the mood match? (color, lighting, style)
3. spatial_coherence: Is the space natural? (no structural distortions)
4. frame_photos: Are wall frames present? Do they match described content?
5. overall_quality: Does it feel like "this person's room"?
```

### 4-3. Regeneration (if needed)

- Low-scoring items → adjust the corresponding part of the prompt
- Missing objects → emphasize them in the prompt
- Mood mismatch → tweak color/lighting keywords
- **Max 3 iterations** (cost/time constraint)

---

## Stage 5: 3D Conversion

### 5-1. World Labs API Call

- **Input**: Final room image from Stage 4 (as image prompt) + supplementary text
- **Model**: `Marble 0.1-plus` (high quality, ~5 min) or `Marble 0.1-mini` (fast test, ~30–45s)
- **Supplementary text**: "A cozy room interior, explorable, with depth"
- **Output**: Gaussian splat + collider mesh + thumbnail + panorama

### 5-2. 3D Room Post-Processing

- Render in browser via Spark (Three.js-based)
- Set initial camera position (room entrance viewpoint)
- Basic interaction: mouse/touch to explore the room

### 5-3. Shareable Link

- Generate unique URL (e.g., `instaroom.xyz/username`)
- Auto-generate OG image (room screenshot)
- Show preview on social share

---

## Output

What the user receives:
1. **3D Room Link** — Explorable "my room" in the browser
2. **Room Screenshot** — Shareable image for SNS
3. **Analysis Summary** — "Based on your Instagram, you are a ___ kind of person"

---

## Cost Estimate (per generation)

| Stage | API | Estimated Cost |
|---|---|---|
| Stage 1 | Gemini 3 Flash × 50–100 posts | ~$0.3–0.5 |
| Stage 2 | Gemini 3 Flash × 1 call | ~$0.01 |
| Stage 3 | Gemini 3 Flash × 3–4 calls | ~$0.05 |
| Stage 4 | Nano Banana Pro × 1–3 calls | TBD (Gemini API pricing) |
| Stage 5 | World Labs × 1 call | TBD (credit-based) |
| **Total** | | **~$1–3 estimated** |

---

## Tech Stack

- **Backend**: Python (FastAPI)
- **Crawling**: Instaloader
- **VLM/LLM**: Gemini 3 Flash (analysis + prompt design + critique)
- **Image Generation**: Nano Banana Pro (Gemini 3 Pro Image Preview)
- **3D Generation**: World Labs API (Marble)
- **3D Rendering**: Spark (Three.js)
- **Frontend**: Next.js or simple static site
- **Hosting**: Vercel (front) + Railway / Fly.io (back)

---

## MVP Scope (1 week)

### Must Have
- [ ] Instagram username → crawl (most recent 20 posts)
- [ ] VLM analysis → aggregated profile
- [ ] Prompt design → Nano Banana Pro room image generation
- [ ] World Labs → 3D room generation
- [ ] Web link to explore the 3D room

### Nice to Have
- [ ] Self-critique loop (1 round)
- [ ] Direct photo upload option
- [ ] OG image + share functionality
- [ ] "You are this kind of person" analysis text

### Phase 2 (if traction)
- [ ] Self-critique loop (3 rounds)
- [ ] Room editing (move/add objects)
- [ ] Visitor mode (explore other people's rooms)
- [ ] Instagram OAuth integration
