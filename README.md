# Telegram Channel AI Rewriter Bot

A bot that **automatically rewrites the description of every new post** you
publish in your Telegram channel (apps, games, APKs, anything) using AI, then
**edits the post in place** with the improved text. Works with any
OpenAI-compatible AI provider (OpenAI, Groq, OpenRouter, Together, Sarvam,
local Ollama, ...).

## How it works

1. You post something in your channel (e.g. an APK with a plain caption).
2. The bot receives the new post (it must be an **admin** of the channel).
3. It sends the text to your AI provider with a prompt tuned for app/software
   posts — it keeps all links, hashtags, versions and file details intact.
4. It edits your post with the rewritten, nicely formatted description.

The bot only reacts to **new** posts. Its own edits arrive as "edited post"
updates, which it ignores — so there is no rewrite loop.

## Files

| File             | Purpose                                          |
|------------------|--------------------------------------------------|
| `bot.py`         | The entire bot (single file)                      |
| `requirements.txt` | Python dependencies                              |
| `.env.example`   | Template for your configuration                   |
| `render.yaml`    | One-click deploy config for Render                |

## Setup (one time, ~10 minutes)

### 1. Create the bot

1. Open Telegram, talk to **@BotFather**, send `/newbot`, follow the steps.
2. Copy the **bot token** it gives you (looks like `123456:ABC-xyz...`).

### 2. Make the bot an admin of your channel

1. In your channel: **Channel Managers → Add Admin →** search your bot's
   @username.
2. In the admin permissions, make sure **Edit Messages** is allowed. This is
   what lets the bot change your posts.
3. If you use a linked discussion group, leave the bot a normal member there;
   it does not need extra rights outside the channel.

### 3. Get your channel ID

- If your channel has a public @username, you can just use that
  (e.g. `@mychannel`).
- Otherwise, forward any message from the channel to **@userinfobot** (or
  **@RawDataBot**) — it replies with the numeric chat id, like
  `-1001234567890`. Use the id that starts with `-100`.

### 4. Get a Gemini API key (free)

1. Go to **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)**,
   sign in with your Google account, and click **Create API key**.
2. That's your `AI_API_KEY`. The free tier is generous (15 requests/minute
   with `gemini-2.5-flash`) — far more than a channel needs.

The bot talks to Gemini through Google's OpenAI-compatible endpoint, so in
`.env` you need:

```
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
AI_MODEL=gemini-2.5-flash
```

Other model options: `gemini-2.5-pro` (highest quality, lower free limits) or
`gemini-2.5-flash-lite` (cheapest and fastest).

**Using a different provider instead?** Any OpenAI-compatible API works —
just change `AI_BASE_URL` and `AI_MODEL`, e.g. OpenAI
(`https://api.openai.com/v1`, `gpt-4o-mini`), Groq
(`https://api.groq.com/openai/v1`), OpenRouter, Together, or local Ollama
(`http://localhost:11434/v1`, key can be anything).

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your values
python bot.py
```

Leave the `WEBHOOK_URL` variable empty for local runs — the bot will use
long polling. Post something in your channel and watch it get rewritten.

## Deploying on Render (free)

1. Push this folder to a GitHub repo (add `.env` to `.gitignore` — never
   commit tokens).
2. On [render.com](https://render.com): **New → Web Service** → connect the
   repo. Render reads `render.yaml` automatically, or set it manually:
   - Runtime: **Python 3**, Build: `pip install -r requirements.txt`,
     Start: `python bot.py`
3. Add environment variables (Render dashboard → Environment):
   `TELEGRAM_BOT_TOKEN`, `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`,
   `CHANNEL_ID`, and `WEBHOOK_URL` = your Render URL, e.g.
   `https://your-service-name.onrender.com`
4. Deploy.

**Free-tier sleep:** Render free web services sleep after ~15 min without
HTTP traffic, which pauses the bot. Two fixes:

- Set up a free [UptimeRobot](https://uptimerobot.com) monitor that pings
  `https://your-service-name.onrender.com/` every 10 minutes, **or**
- Use [Railway](https://railway.app) instead — its free/trial plan keeps a
  worker running. On Railway, set the same env vars and leave `WEBHOOK_URL`
  empty so the bot uses polling; no public URL needed.

## Customizing the writing style

Set the `REWRITE_STYLE` environment variable, e.g.:

```
REWRITE_STYLE=short and punchy, heavy on emojis, aimed at gamers
```

To change the rules the AI follows (e.g. always end with a "How to install"
section), edit the `SYSTEM_PROMPT` in `bot.py`.

## Safety features built in

- Links, hashtags and file facts are preserved by prompt rules.
- If the AI output breaks Telegram's HTML rules, the bot fixes unbalanced
  tags and retries, then falls back to plain text — your post is never lost.
- If the AI call fails (bad key, provider down), the original post is left
  untouched and the error is logged.
- Post length is capped to Telegram's limits (1024 chars for captions,
  4096 for text).

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot doesn't react to posts | It must be an **admin** of the channel with **Edit Messages** on; also check `CHANNEL_ID` matches (or leave it empty). |
| "Forbidden: bot is not an administrator" in logs | Re-check admin rights in channel settings. |
| Edits fail with "message is not modified" | The rewrite matched the original — harmless, ignored. |
| Nothing happens after deploy | Check the Render/Railway logs; usually a missing env var. |
| AI errors | Verify `AI_API_KEY`, `AI_BASE_URL` and `AI_MODEL` match your provider. |
