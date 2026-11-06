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
`cp .env.example .env` and fill in Anthropic, Supabase, Instagram and Pixabay (free at pixabay.com/api/docs).

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
- Photos only from Wikimedia Commons (CC/public domain, file title must match the subject) or Pixabay; otherwise a branded gradient
- Photo credit on the cover and in the caption
- No em or en dashes, enforced in code as well as the prompt
- Checks Instagram's publishing quota before each post
- 72h dedupe by URL and fuzzy title match

## Cross-posting (v2)

After each Instagram carousel goes live, the same post goes out to:

| Channel | What gets posted |
|---|---|
| Instagram Story | The cover, resized to 9:16 |
| Threads | The full carousel, plus a 500-character text |
| X | The headline plus 4 slides, with the rest as a reply |
| LinkedIn | The full carousel as a multi-image post |

Each channel is independent. If one fails, the others still post and the failure is logged in `posts.channels` in Supabase. A channel stays off until its keys are in `.env`.

**One-time database step.** Run this in the Supabase SQL editor:
```sql
alter table posts add column if not exists channels jsonb;
```

### Instagram Story
No setup. It uses the Instagram token you already have.

### Threads (about 15 minutes)
1. Open the same Meta app, go to **Use cases → Add use case → Access the Threads API**.
2. Add the `threads_basic` and `threads_content_publish` permissions.
3. Under **App roles → Roles**, add the Phisify Threads account as a **Threads Tester**. Accept the invite in Threads (Settings → Account → Website permissions).
4. Generate a token for that account. Exchange it for a long-lived token, then put it and the user ID into `.env`.

The token refreshes itself every Monday.

### X (about 20 minutes, paid)
1. Go to developer.x.com and log in as the **Phisify X account**.
2. Create a project and app, set **User authentication → Read and write**, then add credits. X API writes are pay-per-use, roughly $0.015 per post.
3. Under **Keys and tokens**, generate the **API Key and Secret** and the **Access Token and Secret**.
4. Put all four into `.env`.

These keys don't expire. If the account has X Premium, set `X_MAX_CHARS=25000`.

### LinkedIn company page (needs approval)
1. On linkedin.com/developers, create an app linked to the Phisify company page and verify it from the page.
2. Request the **Community Management API** product. LinkedIn reviews it, which can take days to weeks.
3. Once it's approved, run OAuth with the `w_organization_social` scope as a page admin. Put the access and refresh tokens, the client ID and secret, and `LINKEDIN_AUTHOR=urn:li:organization:<page id>` into `.env`.

Access tokens last 60 days, and the engine refreshes them weekly with the refresh token.

### Check it
Dry runs now also write `story.jpg`, `threads.txt`, `x.txt` and `linkedin.txt`, so you can preview every channel before going live.
