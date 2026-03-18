import asyncio
from datetime import datetime
import html
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp
from telegram import (
    BotCommand,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)


logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.WARNING,
)
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TELEGRAM_MESSAGE_LIMIT = 3800
PLAYLIST_TITLE_MAX_LENGTH = 200
VIDEO_TITLE_MAX_LENGTH = 300
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
OUTPUT_MODE_FULL = "full"
OUTPUT_MODE_LINKS_ONLY = "only_links"
SUPPORTED_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

TEXTS = {
    "he": {
        "start": (
            "שלח לי הודעה עם קישור לפלייליסט ביוטיוב, ואני אחזיר לך את כל הסרטונים "
            "כרשימה מסודרת.\n\n"
            "אפשר לשלוח גם כמה פלייליסטים באותה הודעה.\n"
            "לבחירת מצב פלט: /mode"
        ),
        "help": (
            "מה נתמך:\n"
            "• קישור אחד או כמה קישורי פלייליסטים של YouTube\n"
            "• טקסט חופשי סביב הקישורים\n"
            "• פיצול אוטומטי אם התשובה ארוכה מדי\n"
            "• החלפת שפה דרך /language\n"
            "• בחירת מצב פלט דרך /mode\n"
            "• קיצורי דרך: /only_links_mode ו־/full_mode"
        ),
        "language_prompt": "בחר שפה:",
        "language_updated": "השפה הוחלפה לעברית.",
        "mode_prompt": "בחר מצב פלט:\nמצב נוכחי: {current_mode}",
        "mode_updated": "מצב פלט עודכן.\nמצב נוכחי: {current_mode}",
        "mode_label_full": "מלא",
        "mode_label_links_only": "רק לינקים",
        "output_mode_links_only": "מצב פלט הוחלף לקישורים בלבד.",
        "output_mode_full": "מצב פלט הוחלף למצב מלא.",
        "invalid_playlist": "נא לשלוח קישור לפלייליסט ביוטיוב.",
        "processing_error": "לא הצלחתי לקרוא את הפלייליסט הזה כרגע.",
        "playlist_untitled": "פלייליסט ללא שם",
        "video_untitled": "סרטון ללא שם",
        "video_unavailable": "סרטון לא זמין",
        "playlist_empty_links": "לא נמצאו קישורים זמינים בפלייליסט הזה.",
        "part_label": "חלק {current}/{total}",
        "language_button": "שפה",
    },
    "en": {
        "start": (
            "Send me a YouTube playlist link and I will return all videos as a clean list.\n\n"
            "You can also send multiple playlists in one message.\n"
            "To choose output mode: /mode"
        ),
        "help": (
            "Supported:\n"
            "• One or multiple YouTube playlist links\n"
            "• Extra text around the links\n"
            "• Automatic splitting when the reply is too long\n"
            "• Language switching via /language\n"
            "• Output mode selection via /mode\n"
            "• Shortcuts: /only_links_mode and /full_mode"
        ),
        "language_prompt": "Choose a language:",
        "language_updated": "Language switched to English.",
        "mode_prompt": "Choose output mode:\nCurrent mode: {current_mode}",
        "mode_updated": "Output mode updated.\nCurrent mode: {current_mode}",
        "mode_label_full": "Full",
        "mode_label_links_only": "Links only",
        "output_mode_links_only": "Output mode switched to links only.",
        "output_mode_full": "Output mode switched to full mode.",
        "invalid_playlist": "Please send a YouTube playlist link.",
        "processing_error": "I couldn't read this playlist right now.",
        "playlist_untitled": "Untitled playlist",
        "video_untitled": "Untitled video",
        "video_unavailable": "Video unavailable",
        "playlist_empty_links": "No available links were found in this playlist.",
        "part_label": "Part {current}/{total}",
        "language_button": "Language",
    },
}

BOT_COMMANDS = {
    "default": [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Help and examples"),
        BotCommand("language", "Change bot language"),
        BotCommand("mode", "Choose output mode"),
    ],
    "en": [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Help and examples"),
        BotCommand("language", "Change bot language"),
        BotCommand("mode", "Choose output mode"),
    ],
    "he": [
        BotCommand("start", "התחלת הבוט"),
        BotCommand("help", "עזרה ודוגמאות"),
        BotCommand("language", "החלפת שפה"),
        BotCommand("mode", "בחירת מצב פלט"),
    ],
}


def clamp_text(value: str | None, fallback: str, max_length: int) -> str:
    text = (value or "").strip() or fallback
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def detect_default_language(update: Update) -> str:
    user_language_code = (update.effective_user.language_code or "").lower()
    return "he" if user_language_code.startswith("he") else "en"


def get_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    saved_language = context.user_data.get("lang")
    if saved_language in TEXTS:
        return saved_language

    language = detect_default_language(update)
    context.user_data["lang"] = language
    return language


def get_output_mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    output_mode = context.user_data.get("output_mode")
    if output_mode in {OUTPUT_MODE_FULL, OUTPUT_MODE_LINKS_ONLY}:
        return output_mode

    context.user_data["output_mode"] = OUTPUT_MODE_FULL
    return OUTPUT_MODE_FULL


def get_output_mode_label(language: str, output_mode: str) -> str:
    if output_mode == OUTPUT_MODE_LINKS_ONLY:
        return t(language, "mode_label_links_only")
    return t(language, "mode_label_full")


def t(language: str, key: str, **kwargs: Any) -> str:
    template = TEXTS[language][key]
    return template.format(**kwargs)


def get_commands_for_language(language: str) -> list[BotCommand]:
    return BOT_COMMANDS.get(language, BOT_COMMANDS["default"])


def build_language_keyboard(current_language: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                "עברית",
                callback_data="lang:he",
            ),
            InlineKeyboardButton(
                "English",
                callback_data="lang:en",
            ),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def build_mode_keyboard(current_mode: str, language: str) -> InlineKeyboardMarkup:
    full_label = t(language, "mode_label_full")
    links_only_label = t(language, "mode_label_links_only")
    if current_mode == OUTPUT_MODE_FULL:
        full_label = f"[{full_label}]"
    else:
        links_only_label = f"[{links_only_label}]"

    buttons = [
        [
            InlineKeyboardButton(full_label, callback_data=f"mode:{OUTPUT_MODE_FULL}"),
            InlineKeyboardButton(
                links_only_label,
                callback_data=f"mode:{OUTPUT_MODE_LINKS_ONLY}",
            ),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def normalize_url(raw_url: str) -> str:
    return raw_url.rstrip(".,!?;:)]}>\"'")


def extract_urls(text: str) -> list[str]:
    return [normalize_url(match.group(0)) for match in URL_PATTERN.finditer(text or "")]


def extract_playlist_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    hostname = (parsed.hostname or "").lower()
    if hostname not in SUPPORTED_YOUTUBE_HOSTS:
        return None

    query = parse_qs(parsed.query)
    playlist_id = query.get("list", [None])[0]
    if not playlist_id:
        return None

    return playlist_id.strip()


def build_canonical_playlist_url(url: str) -> str | None:
    playlist_id = extract_playlist_id(url)
    if not playlist_id:
        return None
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def build_video_url(entry: dict[str, Any]) -> str | None:
    webpage_url = (entry.get("webpage_url") or "").strip()
    if webpage_url.startswith("http://") or webpage_url.startswith("https://"):
        return webpage_url

    raw_url = (entry.get("url") or "").strip()
    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        return raw_url

    video_id = (entry.get("id") or raw_url).strip()
    if not video_id:
        return None

    return f"https://www.youtube.com/watch?v={video_id}"


def is_unavailable_entry(entry: dict[str, Any], video_url: str | None) -> bool:
    availability = (entry.get("availability") or "").strip().lower()
    if availability and availability not in {"public", "unlisted"}:
        return True

    title = (entry.get("title") or "").strip().lower()
    if title in {"[deleted video]", "private video"}:
        return True

    return video_url is None


def fetch_playlist_data(url: str) -> dict[str, Any]:
    ydl_options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }

    with yt_dlp.YoutubeDL(ydl_options) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise ValueError("Playlist extraction failed")

    playlist_title = clamp_text(
        info.get("title"),
        TEXTS["en"]["playlist_untitled"],
        PLAYLIST_TITLE_MAX_LENGTH,
    )
    raw_entries = info.get("entries") or []
    if not isinstance(raw_entries, list):
        raise ValueError("Playlist entries are missing")

    entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            entries.append(
                {
                    "index": index,
                    "title": None,
                    "url": None,
                    "available": False,
                }
            )
            continue

        video_url = build_video_url(raw_entry)
        title_value = raw_entry.get("title")
        video_title = clamp_text(title_value, "", VIDEO_TITLE_MAX_LENGTH) or None
        entries.append(
            {
                "index": index,
                "title": video_title,
                "url": video_url,
                "available": not is_unavailable_entry(raw_entry, video_url),
            }
        )

    return {"title": playlist_title, "entries": entries}


def format_entry_block(language: str, entry: dict[str, Any]) -> str:
    index = entry["index"]
    title = entry["title"]
    url = entry["url"]

    if entry["available"]:
        safe_title = html.escape(title or t(language, "video_untitled"))
        lines = [f"{index}. {safe_title}"]
        if url:
            lines.append(url)
        return "\n".join(lines)

    unavailable_label = t(language, "video_unavailable")
    if title:
        first_line = f"{index}. {html.escape(unavailable_label)} ({html.escape(title)})"
    else:
        first_line = f"{index}. {html.escape(unavailable_label)}"

    lines = [first_line]
    if url:
        lines.append(url)
    return "\n".join(lines)


def split_links_only_messages(
    language: str,
    entries: list[dict[str, Any]],
    max_length: int = TELEGRAM_MESSAGE_LIMIT,
) -> list[str]:
    links = [entry["url"] for entry in entries if entry.get("url")]
    if not links:
        return [t(language, "playlist_empty_links")]

    messages: list[str] = []
    current_message_parts: list[str] = []
    current_length = 0

    for link in links:
        addition = len(link) if not current_message_parts else len(link) + 2
        if current_message_parts and current_length + addition > max_length:
            messages.append("\n\n".join(current_message_parts))
            current_message_parts = [link]
            current_length = len(link)
            continue

        current_message_parts.append(link)
        current_length += addition

    if current_message_parts:
        messages.append("\n\n".join(current_message_parts))

    return messages


def split_playlist_messages(
    language: str,
    playlist_title: str,
    entry_blocks: list[str],
    max_length: int = TELEGRAM_MESSAGE_LIMIT,
) -> list[str]:
    safe_title = html.escape(
        clamp_text(
            playlist_title,
            t(language, "playlist_untitled"),
            PLAYLIST_TITLE_MAX_LENGTH,
        )
    )
    base_header = f"<b>{safe_title}</b>"
    reserved_for_part_label = 32
    max_body_length = max_length - len(base_header) - reserved_for_part_label - 4

    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_length = 0

    for block in entry_blocks:
        addition = len(block) if not current_chunk else len(block) + 2
        if current_chunk and current_length + addition > max_body_length:
            chunks.append(current_chunk)
            current_chunk = [block]
            current_length = len(block)
            continue

        current_chunk.append(block)
        current_length += addition

    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        chunks = [[]]

    messages: list[str] = []
    total_parts = len(chunks)
    for current_part, chunk in enumerate(chunks, start=1):
        body = "\n\n".join(chunk).strip()
        if total_parts == 1:
            messages.append(f"{base_header}\n\n{body}" if body else base_header)
            continue

        part_label = html.escape(
            t(language, "part_label", current=current_part, total=total_parts)
        )
        if body:
            messages.append(f"{base_header}\n{part_label}\n\n{body}")
        else:
            messages.append(f"{base_header}\n{part_label}")

    return messages


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = get_language(update, context)
    if update.effective_chat:
        await context.bot.set_my_commands(
            get_commands_for_language(language),
            scope=BotCommandScopeChat(update.effective_chat.id),
        )
    await update.message.reply_text(
        t(language, "start"),
        reply_markup=build_language_keyboard(language),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = get_language(update, context)
    await update.message.reply_text(t(language, "help"))


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = get_language(update, context)
    await update.message.reply_text(
        t(language, "language_prompt"),
        reply_markup=build_language_keyboard(language),
    )


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = get_language(update, context)
    output_mode = get_output_mode(context)
    await update.message.reply_text(
        t(
            language,
            "mode_prompt",
            current_mode=get_output_mode_label(language, output_mode),
        ),
        reply_markup=build_mode_keyboard(output_mode, language),
    )


async def only_links_mode_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    language = get_language(update, context)
    context.user_data["output_mode"] = OUTPUT_MODE_LINKS_ONLY
    await update.message.reply_text(t(language, "output_mode_links_only"))


async def full_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = get_language(update, context)
    context.user_data["output_mode"] = OUTPUT_MODE_FULL
    await update.message.reply_text(t(language, "output_mode_full"))


async def language_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    selected_language = query.data.split(":", maxsplit=1)[1]
    if selected_language not in TEXTS:
        return

    context.user_data["lang"] = selected_language
    if update.effective_chat:
        await context.bot.set_my_commands(
            get_commands_for_language(selected_language),
            scope=BotCommandScopeChat(update.effective_chat.id),
        )
    try:
        await query.edit_message_text(t(selected_language, "language_updated"))
    except BadRequest as error:
        if "Message is not modified" not in str(error):
            raise


async def mode_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    selected_mode = query.data.split(":", maxsplit=1)[1]
    if selected_mode not in {OUTPUT_MODE_FULL, OUTPUT_MODE_LINKS_ONLY}:
        return

    context.user_data["output_mode"] = selected_mode
    language = get_language(update, context)
    try:
        await query.edit_message_text(
            t(
                language,
                "mode_updated",
                current_mode=get_output_mode_label(language, selected_mode),
            ),
            reply_markup=build_mode_keyboard(selected_mode, language),
        )
    except BadRequest as error:
        if "Message is not modified" not in str(error):
            raise


async def process_playlist_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    language: str,
    playlist_url: str,
) -> None:
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        playlist_data = await asyncio.to_thread(fetch_playlist_data, playlist_url)
    except Exception:
        LOGGER.exception("Failed to process playlist URL: %s", playlist_url)
        await update.message.reply_text(t(language, "processing_error"))
        return

    output_mode = get_output_mode(context)
    if output_mode == OUTPUT_MODE_LINKS_ONLY:
        messages = split_links_only_messages(language, playlist_data["entries"])
    else:
        entry_blocks = [
            format_entry_block(language, entry) for entry in playlist_data["entries"]
        ]
        messages = split_playlist_messages(
            language=language,
            playlist_title=playlist_data["title"],
            entry_blocks=entry_blocks,
        )

    for message in messages:
        if output_mode == OUTPUT_MODE_LINKS_ONLY:
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)


async def text_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.message.text:
        return

    language = get_language(update, context)
    urls = extract_urls(update.message.text)

    if not urls:
        await update.message.reply_text(t(language, "invalid_playlist"))
        return

    for url in urls:
        playlist_url = build_canonical_playlist_url(url)
        if not playlist_url:
            await update.message.reply_text(t(language, "invalid_playlist"))
            continue

        await process_playlist_url(update, context, language, playlist_url)


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    LOGGER.exception("Unhandled exception while processing update", exc_info=context.error)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS["default"])
    await application.bot.set_my_commands(BOT_COMMANDS["en"], language_code="en")
    await application.bot.set_my_commands(BOT_COMMANDS["he"], language_code="he")


def build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    data_dir = Path("bot_data")
    data_dir.mkdir(exist_ok=True)
    persistence = PicklePersistence(filepath=str(data_dir / "persistence.pkl"))

    application = (
        Application.builder()
        .token(token)
        .persistence(persistence)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("language", language_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CommandHandler("only_links_mode", only_links_mode_command))
    application.add_handler(CommandHandler("full_mode", full_mode_command))
    application.add_handler(CallbackQueryHandler(language_button_handler, pattern=r"^lang:"))
    application.add_handler(CallbackQueryHandler(mode_button_handler, pattern=r"^mode:"))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler)
    )
    application.add_error_handler(error_handler)

    return application


def main() -> None:
    application = build_application()
    startup_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOGGER.info("Bot is running and ready at %s", startup_time)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
