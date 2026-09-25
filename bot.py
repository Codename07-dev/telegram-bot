"""
Telegram Channel AI Rewriter Bot
================================
Automatically rewrites the description/caption of every new post you
publish in your Telegram channel, using any OpenAI-compatible AI API
(OpenAI, Groq, OpenRouter, Together, Sarvam, a local Ollama server, etc.),
then edits the post in place with the improved text.

Requirements:
  - A bot token from @BotFather
  - The bot must be an ADMIN of your channel with "Edit Messages" enabled
  - An API key for any OpenAI-compatible provider
"""

import logging
import os
import re
import sys

# Load a local .env file if present (harmless in production, where real
# environment variables are set by the platform).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


from openai import OpenAI
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ----------------------------------------------------------------------------
# Configuration (all via environment variables)
# ----------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
# AI provider - Gemini by default. Gemini exposes an OpenAI-compatible
# endpoint, so any other OpenAI-compatible provider also works by changing
# AI_BASE_URL and AI_MODEL (OpenAI, Groq, OpenRouter, Together, Ollama, ...).
AI_BASE_URL = os.environ.get(
    "AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
).strip()
AI_MODEL = os.environ.get("AI_MODEL", "gemini-2.5-flash").strip()

# Optional: only react to posts from this channel (numeric id like -1001234567890
# or a public @username). Leave empty to react to every channel the bot is in.
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()

# Optional: webhooks (needed for Render free tier). If WEBHOOK_URL is set,
# the bot runs in webhook mode; otherwise it uses long polling (local runs).
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
PORT = int(os.environ.get("PORT", "8443"))

MAX_CAPTION_LEN = 1024  # Telegram hard limit for captions
MAX_TEXT_LEN = 4096    # Telegram hard limit for text messages

# The instruction given to the AI. Override the style via the
# REWRITE_STYLE environment variable without touching the code.
REWRITE_STYLE = os.environ.get(
    "REWRITE_STYLE",
    "engaging, professional, and easy to read, with tasteful emoji section "
    "headers and clean formatting",
)

SYSTEM_PROMPT = f"""You are an expert copywriter for a Telegram channel that \
shares apps, games, APKs and software.

You will receive the text of a channel post (it may be the caption of a \
photo/video/document post). Rewrite it so it is {REWRITE_STYLE}.

STRICT RULES:
1. Keep the meaning and every fact: app name, version, size, requirements, \
features, file details.
2. Preserve ALL links, URLs, @usernames, and hashtags EXACTLY as given.
3. If a download link or button text is present, keep it on its own line.
4. Use Telegram HTML formatting only: <b>, <i>, <u>, <s>, <code>, <a href>. \
No Markdown, no LaTeX, no code fences.
5. Do NOT invent features, ratings, or details that are not in the original.
6. Reply with ONLY the rewritten post text. No preamble, no quotes, no \
explanations.
7. Keep it within Telegram's limits: the rewritten post must not be longer \
than the original by more than 20%.
"""


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("rewriter-bot")


# ----------------------------------------------------------------------------
# AI helper
# ----------------------------------------------------------------------------

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Lazily create the OpenAI-compatible client."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    return _client


def strip_code_fence(text: str) -> str:
    """Remove ```html ... ``` fences some models like to add."""
    text = text.strip()
    m = re.fullmatch(r"```(?:html|xml|text)?\s*(.*?)\s*```", text, re.DOTALL)
    return m.group(1).strip() if m else text


def rewrite_with_ai(original: str, max_len: int) -> str:
    """Send the original post text to the AI and get a rewrite back."""
    response = get_client().chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Rewrite this Telegram channel post (output must be "
                    f"under {max_len} characters):\n\n{original}"
                ),
            },
        ],
        temperature=0.6,
        max_tokens=1600,
    )
    result = strip_code_fence(response.choices[0].message.content or "")
    if not result:
        raise ValueError("AI returned an empty rewrite")
    return result


def escape_if_unbalanced(text: str) -> str:
    """Best-effort fix for unbalanced HTML tags the model may produce.

    Scans the string, remembers the order tags were opened in, and appends
    the missing closing tags in reverse (LIFO) order so nesting is valid.
    """
    stack: list[str] = []
    for m in re.finditer(r"</?(b|i|u|s|code|pre|a)(\s[^>]*)?>", text):
        tag = m.group(1)
        if m.group(0).startswith("</"):
            if tag in stack:
                stack.remove(tag)  # tolerate stray closes / wrong nesting
        else:
            stack.append(tag)
    for tag in reversed(stack):
        text += f"</{tag}>"
    return text


def strip_all_html(text: str) -> str:
    """Plain-text fallback if Telegram rejects the HTML."""
    text = re.sub(r"<br\s*/?>", "\n", text)
    return re.sub(r"<[^>]+>", "", text)


# ----------------------------------------------------------------------------
# Telegram handlers
# ----------------------------------------------------------------------------


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Hi! I'm the channel description rewriter.\n"
        "Add me as an *admin* (with 'Edit Messages' allowed) to your "
        "channel, and I'll automatically rewrite every new post you "
        "publish there with AI.",
    )


def _from_allowed_chat(chat) -> bool:
    if not CHANNEL_ID:
        return True
    cid = CHANNEL_ID.lstrip("-")
    if chat.username and chat.username.lower() == CHANNEL_ID.lstrip("@").lower():
        return True
    return str(chat.id).lstrip("-") == cid or str(chat.id) == CHANNEL_ID


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle every NEW post in a channel where the bot is admin."""
    msg = update.channel_post
    if msg is None:
        return

    chat = msg.chat
    if not _from_allowed_chat(chat):
        return

    original = msg.caption if msg.caption else msg.text
    is_caption = bool(msg.caption)
    max_len = MAX_CAPTION_LEN if is_caption else MAX_TEXT_LEN

    if not original or not original.strip():
        log.info("Post %s in %s has no text/caption - nothing to rewrite.",
                 msg.message_id, chat.title or chat.id)
        return

    log.info("Rewriting post %s from '%s' (%d chars)",
             msg.message_id, chat.title or chat.id, len(original))

    # 1. Ask the AI for a rewrite (run in a thread so we don't block the loop)
    try:
        rewritten = await context.application.create_task(
            _rewrite_async(original, max_len)
        )
    except Exception as exc:  # noqa: BLE001
        log.error("AI rewrite failed, leaving post untouched: %s", exc)
        return

    if len(rewritten) > max_len:
        rewritten = rewritten[: max_len - 3].rstrip() + "…"
        log.warning("Rewrite exceeded %d chars and was truncated.", max_len)

    # 2. Edit the original post
    try:
        if is_caption:
            await msg.edit_caption(caption=rewritten, parse_mode=ParseMode.HTML)
        else:
            await msg.edit_text(rewritten, parse_mode=ParseMode.HTML)
        log.info("Post %s rewritten and edited successfully.", msg.message_id)
    except BadRequest as exc:
        # Often: unbalanced HTML or 'message is not modified'
        err = str(exc).lower()
        if "not modified" in err:
            return  # nothing changed, fine
        if "can't parse entities" in err:
            log.warning("HTML rejected (%s) - retrying with fixed tags.", exc)
        else:
            log.error("Edit failed: %s", exc)
            return

        # Retry once: fix tags, then fall back to plain text
        fixed = escape_if_unbalanced(rewritten)
        try:
            if is_caption:
                await msg.edit_caption(caption=fixed, parse_mode=ParseMode.HTML)
            else:
                await msg.edit_text(fixed, parse_mode=ParseMode.HTML)
        except BadRequest:
            plain = strip_all_html(rewritten)
            try:
                if is_caption:
                    await msg.edit_caption(caption=plain)
                else:
                    await msg.edit_text(plain)
            except TelegramError as exc:
                log.error("Final plain-text edit also failed: %s", exc)
    except TelegramError as exc:
        log.error("Edit failed: %s", exc)


async def _rewrite_async(original: str, max_len: int) -> str:
    """Wrapper so the blocking OpenAI call can be scheduled as a task."""
    return await _run_sync(lambda: rewrite_with_ai(original, max_len))


async def _run_sync(fn):
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn)


def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception while processing update:", exc_info=context.error)


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


def main() -> None:
    missing = [name for name in ("TELEGRAM_BOT_TOKEN", "AI_API_KEY")
               if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing required environment variables: {', '.join(missing)}. "
                 "See .env.example for the full list.")

    app: Application = (
        ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    )

    # Private-chat helpers
    app.add_handler(CommandHandler("start", start))

    # New posts in channels where the bot is an admin.
    # Only 'channel_post' is handled - the bot's own edits arrive as
    # 'edited_channel_post', so there is no rewrite loop.
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, on_channel_post))

    app.add_error_handler(on_error)

    if WEBHOOK_URL:
        # Render / Railway / any host with a public HTTPS URL
        log.info("Starting in WEBHOOK mode at %s", WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL.rstrip('/')}/{TELEGRAM_BOT_TOKEN}",
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
    else:
        log.info("Starting in POLLING mode.")
        app.run_polling(drop_pending_updates=True, allowed_updates=["message",
                                                                     "channel_post"])


if __name__ == "__main__":
    main()
