# begone

A Discord bot that auto-detects and bans the **"crypto-casino giveaway"** image-spam wave (the fake *Kai Cenat* tweet + fake *"Withdrawal Success!"* USDT screenshot).

These bots join a server and post 2–4 images across every public channel they can write in, within seconds. begone correlates that cross-channel image burst with an actual content check on the images before it acts — so a single off-topic meme never gets someone banned.

## How it works

1. **Burst tracking** — per user, begone keeps a sliding window of image posts (timestamp + channel).
2. **Content match** — when an image needs checking, it runs two independent signals:
   - **OCR** (`tesseract`) — fuzzy-matches known scam phrases ("Withdrawal Success", "Enter Wallet Address", "promo code"…), tolerant of photo-of-a-screen noise.
   - **Perceptual hash** — compares the image to known samples in `samples/`, robust to recompression/resizing.

   An image matches if *either* signal fires. The two are complementary: phash catches recompressed reposts; OCR catches crops/reframes where the hash drifts.
3. **Action** — on a confirmed spammer: log + alert the mod channel, and (if enabled) ban/kick and delete their messages. Admins, mods, bots, and allow-listed roles/users are never touched.

## Setup

Requires **Python 3.11+** and the **tesseract** OCR engine.

Install tesseract:
- **Linux:** `sudo apt install tesseract-ocr`
- **macOS:** `brew install tesseract`
- **Windows:** `scoop install tesseract` (or the [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki))

> If you install tesseract but get *"Failed loading language 'eng'"*, you're missing the language data. Grab [`eng.traineddata`](https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata) into tesseract's `tessdata/` directory.

Install and configure begone:

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows:     .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env      # then edit it (see below)
python main.py
```

Or install it as a package and use the `begone` command (it reads `config.yaml`, `.env`, and `samples/` from the directory you run it in):

```sh
pip install -e .
begone
```

### Discord bot setup
1. Create an app at <https://discord.com/developers/applications> → **Bot** → **Reset Token** to reveal the token.
2. On the **Bot** page, enable both privileged intents: **Message Content** and **Server Members**.
3. Invite it with these permissions: *View Channels, Send Messages, Embed Links, Read Message History, Manage Messages, Kick Members, Ban Members*.
4. Put the bot's role **above** the spammers' roles in Server Settings → Roles, or it can't ban them.

### `.env`
```
DISCORD_TOKEN=your-bot-token
ALERT_CHANNEL_ID=123456789012345678   # channel for detection alerts
TESSERACT_CMD=                         # blank = auto-discover on PATH
```

## Configuration (`config.yaml`)

Everything is tunable without touching code. Defaults are safe — it starts in **dry-run** (alerts only, no bans).

| key | what it does |
|-|-|
| `action` | `dry_run` (alert only), `ban`, or `kick`. **Start with `dry_run`** to tune against real traffic. |
| `delete_on_action` | Also delete the flagged messages when acting. |
| `ban_delete_message_days` | On ban, delete the user's messages from the last N days (0–7; 0 = none, 1 = 24h, 7 = a week). |
| `scan.mode` | `burst` = only OCR after burst thresholds (cheap, recommended). `always` = OCR every image; a single scam image is enough to act. |
| `burst.window_seconds` | Sliding window for correlating a user's image posts. |
| `burst.min_distinct_channels` | Trigger if images were posted in ≥ this many channels… |
| `burst.min_image_messages` | …or ≥ this many image messages, within the window. |
| `fingerprint.min_keyword_hits` | OCR keyword hits required for a match. |
| `fingerprint.max_phash_distance` | Max perceptual-hash distance (0–64) to a sample for a match. Lower = stricter. |
| `fingerprint.require_image_match` | If false (burst mode only), the burst behaviour alone is enough — no image check. |
| `cache.enabled` / `cache.max_entries` | Bounded LRU cache of per-image verdicts so duplicate/re-posted images aren't re-processed. |
| `exemptions.*` | Skip admins, moderators, bots, and specific role/user IDs. |
| `ocr.upscale` / `ocr.max_bytes` | OCR pre-scale factor and max image size to download. |

### Choosing a scan mode
- **`burst` (default):** lowest CPU and lowest false-positive risk. The bot only spends OCR cycles on users already behaving like spammers (posting across multiple channels fast). Best for most servers.
- **`always`:** scans every posted image. Catches a lone scam image that didn't burst, at the cost of running OCR on all image traffic. Use on smaller/quieter servers or where even single-image scam posts matter.

## Tuning offline

Test the matcher against local images without running the bot:

```sh
python tools/eval.py path/to/image_or_folder
```

It prints OCR keyword hits and phash distance per image, so you can set `min_keyword_hits` / `max_phash_distance` confidently.

## Adding new scam variants
- Drop a clean copy of a new recurring scam image into `samples/` — it's loaded as a reference hash on startup.
- Add new text phrases to `KEYWORD_PHRASES` in `begone/fingerprint.py`.

## Deploy 24/7
A `Dockerfile` is included with tesseract baked in:

```sh
docker build -t begone .
docker run -d --restart=unless-stopped --env-file .env begone
```

## Project layout
| path | purpose |
|-|-|
| `begone/config.py` | YAML + `.env` configuration |
| `begone/detector.py` | per-user sliding-window burst tracker |
| `begone/fingerprint.py` | scam keyword phrases + reference phash loading |
| `begone/ocr.py` | OCR + perceptual-hash matcher |
| `begone/cache.py` | bounded LRU verdict cache |
| `begone/actions.py` | enforcement + mod-channel alerts |
| `begone/bot.py` | discord.py client wiring it together |
| `tools/eval.py` | offline matcher tester |
| `samples/` | reference scam images |

## Notes
- Never commit your `.env` — it holds the bot token. `.gitignore` already excludes it.
- begone only ever **adds** moderation; it makes no outbound requests beyond Discord and downloading the posted images it inspects.
