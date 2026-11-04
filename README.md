# Phisify Meta Engine (Day 1: news carousels)

Posts one Coinsauce-style news carousel to Instagram 3 times a day with no human in the loop.

**Each run:** pull 12 RSS feeds, drop anything already covered, Claude picks the strongest story for today's pillar mix, writes a cover plus 3 to 4 slides plus "why it matters", a second Claude pass fact-checks every claim against the full article, a licence-safe photo is found, slides render at 1080x1350, images go to Supabase Storage, the carousel publishes, and everything is logged.

If a story fails the fact-check, it tries the next one (up to 3). If nothing passes, it posts nothing. Silence beats a wrong post.

## Setup (about 30 minutes)

**1. Supabase**
Run `schema.sql` in the SQL editor. It creates `posts`, `settings` and a public `meta-engine` bucket.

**2. Instagram token**
- The Phisify Instagram account must be a professional (Business or Creator) account.
- In your Meta developer app, add the Instagram product and use **API setup with Instagram login**.
- Give the Phisify account a role on the app (Instagram tester). Development mode is enough for your own account.
- Generate a token with `instagram_business_basic` and `instagram_business_content_publish`.
- Copy the long-lived token and the IG user ID into `.env`.

The token refreshes itself every Monday at 03:10 and the fresh copy is stored in Supabase, so you only paste it once.

**3. Keys**
`cp .env.example .env` and fill in Anthropic, Supabase, Instagram and Pexels (free at pexels.com/api).

**4. Dry run first**
```bash
docker compose build
docker compose run --rm meta-engine python -m engine.main run --dry
```
Slides and `caption.txt` land in `./out/<run-id>/`. Run it 3 or 4 times and read the output.

**5. Go live**
Set `DRY_RUN=false` in `.env`, then:
```bash
docker compose up -d
```

## Running it

| Command | What it does |
|---|---|
| `docker compose logs -f` | Watch runs |
| `docker compose exec meta-engine python -m engine.main pause` | Kill switch. Stops posting instantly |
| `docker compose exec meta-engine python -m engine.main resume` | Turn it back on |
| `docker compose exec meta-engine python -m engine.main run` | Force one post now |

The `posts` table is the audit trail. Every rejected story has its `reason`, which is the best data for tuning the prompts.

## Tuning without code

`config/engine.yaml` controls feeds, pillar mix, webinar themes, CTA, brand handle and accent colour. It is mounted as a volume, so edits apply on the next run.

## Guardrails built in

- Every number must exist in the article or the live CoinGecko snapshot, checked by a separate model pass
- No price calls, no investment advice, allegations stay allegations
- Skips deaths, violence, disasters, sponsored posts, opinion pieces
- Skips stories it can't read in full (it won't post what it can't verify)
- Photos only from Wikimedia Commons (CC/public domain, file title must match the subject) or Pexels; otherwise a branded gradient
- Photo credit on the cover and in the caption
- No em or en dashes, enforced in code as well as the prompt
- Checks Instagram's publishing quota before each post
- 72h dedupe by URL and fuzzy title match
