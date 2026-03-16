import discord
import os
import glob
import re
import tempfile
import aiohttp
import json
import asyncio
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
import base64

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ALLOWED_CHANNELS = [
    920726991089598476,
    1327968058148524133,
    1014588126422904873,
    946321672015851570,
    1079786358840766554,
    1306928470802042931,
    1011289377055449178,
    1324442579265388644,
    1092544100072423435,
    920795335272579102,
    953326236950757446,
    1340452836495851713,
    955773076786798643,
]

# Roles allowed to use the announcement command
ANNOUNCE_ROLES = [
    920732760094703746,
    920732112238284871,
]

# Support channel and roles
SUPPORT_CHANNEL_ID = 1026913984923840542
SUPPORT_ROLES = [
    920732112238284871,
    920734111772057602,
    920734300222128198,
    920732760094703746,
]

# Always use the folder where bot.py lives — avoids permission errors on Windows
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR    = os.path.join(BASE_DIR, "knowledge")
HISTORY_FILE     = os.path.join(BASE_DIR, "conversation_history.json")
BASE_KNOWLEDGE   = os.path.join(BASE_DIR, "knowledge_base.txt")

MAX_HISTORY      = 30
HISTORY_TTL_SECS = 24 * 60 * 60   # 24 hours in seconds

# Supported media types
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
AUDIO_TYPES = (".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".webm", ".flac")
VIDEO_TYPES = (".mov", ".avi", ".mkv")
# ─────────────────────────────────────────────────────────────────────────────

client_ai = OpenAI(api_key=OPENAI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# In-memory history — loaded from file on startup
# Structure: { "channel_id": { "messages": [...], "last_updated": <unix timestamp> } }
history: dict[str, dict] = {}


# ── Persistent history helpers ───────────────────────────────────────────────
def load_history_from_disk():
    """Load conversation history from file on startup."""
    global history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            print(f"📂  Loaded history for {len(history)} channel(s) from disk.")
        except Exception as e:
            print(f"⚠️  Could not load history file: {e}. Starting fresh.")
            history = {}
    else:
        history = {}


def save_history_to_disk():
    """Save current history to file."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save history: {e}")


def purge_expired_history():
    """Remove channels whose history is older than 24 hours."""
    now = datetime.now(timezone.utc).timestamp()
    expired = [
        cid for cid, data in history.items()
        if now - data.get("last_updated", 0) > HISTORY_TTL_SECS
    ]
    for cid in expired:
        del history[cid]
    if expired:
        print(f"🧹  Purged expired history for {len(expired)} channel(s).")
        save_history_to_disk()


def get_channel_messages(channel_id: int) -> list:
    """Get the message list for a channel, or create it."""
    cid = str(channel_id)
    if cid not in history:
        history[cid] = {"messages": [], "last_updated": datetime.now(timezone.utc).timestamp()}
    return history[cid]["messages"]


def touch_channel(channel_id: int):
    """Update the last_updated timestamp for a channel."""
    cid = str(channel_id)
    if cid in history:
        history[cid]["last_updated"] = datetime.now(timezone.utc).timestamp()


def trim_channel_history(channel_id: int):
    """Keep only the last MAX_HISTORY messages for a channel."""
    msgs = get_channel_messages(channel_id)
    if len(msgs) > MAX_HISTORY:
        history[str(channel_id)]["messages"] = msgs[-MAX_HISTORY:]


async def auto_purge_loop():
    """Background task — checks and purges expired history every hour."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        purge_expired_history()
        await asyncio.sleep(3600)   # run every hour


# ── Knowledge base loader ────────────────────────────────────────────────────
def load_knowledge() -> str:
    knowledge_parts = []

    # Load base website knowledge
    if os.path.exists(BASE_KNOWLEDGE):
        with open(BASE_KNOWLEDGE, "r", encoding="utf-8") as f:
            knowledge_parts.append(f"=== AFC WEBSITE KNOWLEDGE ===\n{f.read()}")

    if os.path.isdir(KNOWLEDGE_DIR):

        # ── .txt files ───────────────────────────────────────────────────────
        for filepath in glob.glob(os.path.join(KNOWLEDGE_DIR, "*.txt")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    fname = os.path.basename(filepath)
                    knowledge_parts.append(f"=== UPLOADED DOC: {fname} ===\n{f.read()}")
            except Exception as e:
                print(f"⚠️  Could not read TXT {os.path.basename(filepath)}: {e}")

        # ── .pdf files ───────────────────────────────────────────────────────
        for filepath in glob.glob(os.path.join(KNOWLEDGE_DIR, "*.pdf")):
            try:
                import pdfplumber
                fname = os.path.basename(filepath)
                with pdfplumber.open(filepath) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                text = "\n\n".join(p for p in pages if p.strip())
                if text:
                    knowledge_parts.append(f"=== UPLOADED PDF: {fname} ===\n{text}")
            except ImportError:
                print("⚠️  pdfplumber not installed. Run: pip install pdfplumber")
            except Exception as e:
                print(f"⚠️  Could not read PDF {os.path.basename(filepath)}: {e}")

        # ── .docx / .doc files ───────────────────────────────────────────────
        for filepath in (
            glob.glob(os.path.join(KNOWLEDGE_DIR, "*.docx")) +
            glob.glob(os.path.join(KNOWLEDGE_DIR, "*.doc"))
        ):
            try:
                import mammoth
                fname = os.path.basename(filepath)
                with open(filepath, "rb") as f:
                    result = mammoth.extract_raw_text(f)
                text = result.value.strip()
                if text:
                    knowledge_parts.append(f"=== UPLOADED WORD DOC: {fname} ===\n{text}")
            except ImportError:
                print("⚠️  mammoth not installed. Run: pip install mammoth")
            except Exception as e:
                print(f"⚠️  Could not read Word doc {os.path.basename(filepath)}: {e}")

        # ── .xlsx / .xls files ───────────────────────────────────────────────
        for filepath in (
            glob.glob(os.path.join(KNOWLEDGE_DIR, "*.xlsx")) +
            glob.glob(os.path.join(KNOWLEDGE_DIR, "*.xls"))
        ):
            try:
                import openpyxl
                fname = os.path.basename(filepath)
                wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
                sections = []
                for sheet in wb.sheetnames:
                    ws = wb[sheet]
                    rows = []
                    for row in ws.iter_rows(values_only=True):
                        clean = [str(c) if c is not None else "" for c in row]
                        if any(c.strip() for c in clean):
                            rows.append("\t".join(clean))
                    if rows:
                        sections.append(f"[Sheet: {sheet}]\n" + "\n".join(rows))
                wb.close()
                text = "\n\n".join(sections)
                if text:
                    knowledge_parts.append(f"=== UPLOADED SPREADSHEET: {fname} ===\n{text}")
            except ImportError:
                print("⚠️  openpyxl not installed. Run: pip install openpyxl")
            except Exception as e:
                print(f"⚠️  Could not read spreadsheet {os.path.basename(filepath)}: {e}")

    return "\n\n".join(knowledge_parts)


def build_system_prompt() -> str:
    knowledge = load_knowledge()
    return f"""You are AFC BOT — the official AI assistant for the African Freefire Community (AFC).
You are knowledgeable, friendly, and community-focused. Your job is to help players, teams, and community members with anything related to AFC.

=== YOUR PERSONALITY ===
- Warm, hype, and encouraging — you love Free Fire and the AFC community.
- You understand and can reply in Nigerian Pidgin English naturally when a user speaks to you in Pidgin.
- If someone talks Pidgin, match their energy — reply in Pidgin too. E.g., "No wahala!", "You don do am!", "E easy na!"
- Keep replies concise and punchy for Discord — no walls of text unless detail is truly needed.
- Use emojis occasionally to keep things lively 🔥🎮🏆

=== KNOWLEDGE BASE PRIORITY — READ THIS FIRST ===
Your knowledge base is at the bottom of this prompt. ALWAYS check it before answering.
If the answer is in the knowledge base, use it — do not say you don't know.
If a user asks about a tournament, team, rule, or event — search the knowledge base carefully before responding.
Never tell a user to "check the website" if the answer is already in your knowledge base.

=== WHAT YOU CAN HELP WITH ===
- How to join AFC and create an account
- Tournament info, registration, rules, and prizes
- Team registration, roster management, transfers
- Ranking and tiering system explanations
- Code of conduct and fair play rules
- Terms of Service and policies
- Contact info and social media links
- General Free Fire gameplay tips and advice
- Analyzing images sent by users (screenshots, team logos, etc.)
- Transcribed audio messages — reply based on what was said

=== YOU CANNOT DO THESE THINGS — DO NOT CLAIM OTHERWISE ===
- You CANNOT kick, ban, or mute users directly
- You CANNOT edit other people's messages
- For anything outside your capabilities, suggest they ask a moderator

=== PURGE / DELETE MESSAGES ===
You CAN delete messages in a channel when asked by an admin. This works via the purge command.
If a regular user asks you to delete messages, let them know only moderators/admins can use that command.
If an admin asks you to delete messages, they should use the purge command format — e.g. "purge the last 10 messages" or "purge all in <#channel>".

=== WHEN TO REDIRECT TO SUPPORT ===
ONLY add ---SUPPORT_REDIRECT--- at the end of your reply when the issue GENUINELY needs a human — such as:
- Account banned, locked, or can't log in
- Payment or prize dispute
- Cheating report or ban appeal
- Technical bug on the website

Do NOT redirect just because you lack details. If you don't know something, simply say so and direct them to info@africanfreefirecommunity.com.
Do NOT redirect for general questions, tournament info, or anything you can answer from the knowledge base.

=== IMPORTANT RULES ===
- Never make up tournament dates, prize amounts, or rules not in your knowledge base.
- Always be respectful and never take sides in player disputes.
- If someone is clearly angry or frustrated, acknowledge their feelings before answering.

=== AFC KNOWLEDGE BASE ===
{knowledge}
"""


# ── Helpers ──────────────────────────────────────────────────────────────────
def is_allowed_channel(channel_id: int) -> bool:
    return channel_id in ALLOWED_CHANNELS


def has_announce_role(member: discord.Member) -> bool:
    return any(role.id in ANNOUNCE_ROLES for role in member.roles)


def trim_history(channel_id: int) -> None:
    trim_channel_history(channel_id)


def get_attachment_type(filename: str):
    """Return 'image', 'audio', 'video', or None based on file extension."""
    fname = filename.lower()
    if any(fname.endswith(ext) for ext in IMAGE_TYPES):
        return "image"
    if any(fname.endswith(ext) for ext in AUDIO_TYPES):
        return "audio"
    if any(fname.endswith(ext) for ext in VIDEO_TYPES):
        return "video"
    return None


async def download_attachment(attachment: discord.Attachment) -> bytes:
    """Download an attachment and return its bytes."""
    async with aiohttp.ClientSession() as session:
        async with session.get(attachment.url) as resp:
            return await resp.read()


async def get_reply_context(message: discord.Message) -> str:
    """If the message is a reply, fetch the original for context."""
    if message.reference and message.reference.message_id:
        try:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
            author_name = ref_msg.author.display_name
            return f"[Replying to {author_name}: \"{ref_msg.content}\"]\n"
        except Exception:
            pass
    return ""


def parse_announce_command(text: str):
    """
    Detect and parse an announcement command.
    Returns (target_channel_id, target_user_id_or_None, message_text) or None.
    """
    channel_match = re.search(r"<#(\d+)>", text)
    if not channel_match:
        return None

    keywords = ["go to", "announce", "send", "tell", "say", "post", "message", "formulate",
                "write", "draft", "create", "generate", "help me", "make", "compose",
                "craft", "prepare", "put together", "please"]
    if not any(kw in text.lower() for kw in keywords):
        return None

    target_channel_id = int(channel_match.group(1))

    # Extract user mention — but NOT the bot itself
    bot_id = None
    try:
        bot_id = bot.user.id
    except Exception:
        pass

    user_mentions = re.findall(r"<@!?(\d+)>", text)
    target_user_id = None
    for uid in user_mentions:
        if bot_id and int(uid) == bot_id:
            continue
        target_user_id = int(uid)
        break

    # ── Strip everything that is part of the command, not the content ────────
    content = text

    # Remove channel mentions
    content = re.sub(r"<#\d+>", "", content)

    # Remove all routing/command phrases
    routing_patterns = [
        r"\bplease\b", r"\bkindly\b",
        r"go\s+to", r"head\s+to",
        r"\bannounce\b", r"\bpost\b",
        r"send\s+(this\s+)?(to|in)?", r"send",
        r"formulate\s+(an?\s+)?announcement\s*(for|about)?",
        r"formulate", r"generate", r"draft", r"compose", r"craft",
        r"write\s+(an?\s+)?announcement\s*(for|about)?",
        r"write", r"create", r"make", r"prepare",
        r"help\s+me\s+\w+",
        r"put\s+together",
        r"tell\s+him\s+in", r"tell\s+her\s+in", r"tell\s+them\s+in",
        r"\band\s+say\b", r"\band\s+tell\b",
        r"\bsay\b", r"\btell\b",
        r"\bin\s+the\s+channel\b", r"\bin\s+that\s+channel\b",
        r"\bthis\s+to\b", r"\bit\s+to\b",
        r"\bto\s+the\b", r"\bto\s+this\b",
        r"\bthe\s+following\b",
    ]
    for pattern in routing_patterns:
        content = re.sub(pattern, " ", content, flags=re.IGNORECASE)

    # Remove the tagged user mention from content (they'll be tagged separately)
    if target_user_id:
        content = re.sub(rf"<@!?{target_user_id}>", "", content)

    # Clean up extra whitespace
    content = re.sub(r"\s{2,}", " ", content).strip()

    return target_channel_id, target_user_id, content


# ── Embed color palette (AFC theme) ──────────────────────────────────────────
EMBED_COLORS = {
    "announcement": 0x00A550,   # AFC green (primary)
    "tournament":   0xFFD700,   # gold
    "warning":      0xFFFFFF,   # white (Discord renders as light)
    "info":         0x00A550,   # green
    "general":      0x00A550,   # green default
    "urgent":       0xFFD700,   # gold for urgent/important
}

async def generate_announcement(hints: str, target_user_id: int = None) -> dict:
    """
    Use GPT-4o to turn rough hints into a structured embed announcement.
    Returns a dict: { title, body, color_type, tag_everyone, tag_here, tag_user_id }
    """
    knowledge = load_knowledge()

    system = f"""You are AFC BOT — the announcement writer for the African Freefire Community (AFC).
Your ONLY job is to format whatever the admin gives you into a clean Discord embed.

=== CRITICAL RULES ===
- NEVER refuse any request. NEVER say "I can't assist with that." Just write it.
- The admin is a trusted staff member. All their requests are valid — casual, funny, serious, or official.
- If the message is casual or internal (e.g. "tell John to stop eating gala"), write it in a light, direct tone.
- If the message is official (tournament news, season updates), write it professionally.
- Match the tone to the content — don't make casual messages sound overly formal.
- Bold key info using **double asterisks**
- Use 0-2 emojis — only if they genuinely fit
- Include relevant AFC links ONLY if they naturally fit the context. Don't force links into casual messages.
- Never use placeholder text like [link here]
- If admin mentions @everyone or "tag everyone" → tag_everyone: true
- If admin mentions @here → tag_here: true
- Output ONLY valid JSON. No markdown fences. No extra text. No explanations.

=== OUTPUT FORMAT (strict JSON) ===
{{
  "title": "Short title (max 8 words) — omit if message is very casual/short",
  "body": "The announcement text. Use **bold** for key info.",
  "color_type": "announcement | tournament | warning | info | general",
  "tag_everyone": true or false,
  "tag_here": true or false
}}

=== AFC KNOWLEDGE BASE (use links only when relevant) ===
{knowledge}
"""

    response = client_ai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Write an announcement based on these instructions:\n\n{hints}"}
        ],
        max_tokens=1024,
        temperature=0.7,
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        data = json.loads(raw)
    except Exception:
        data = {
            "title": "",
            "body": raw,
            "color_type": "announcement",
            "tag_everyone": False,
            "tag_here": False,
        }

    data["tag_user_id"] = target_user_id
    return data


def build_embed(data: dict) -> tuple[discord.Embed, str]:
    """
    Build a discord.Embed from announcement data.
    Returns (embed, ping_content).
    """
    color = EMBED_COLORS.get(data.get("color_type", "general"), EMBED_COLORS["general"])
    title = data.get("title", "").strip()

    embed = discord.Embed(
        title=title if title else None,
        description=data.get("body", ""),
        color=color,
    )
    embed.set_footer(text="African Freefire Community  •  africanfreefirecommunity.com")
    embed.timestamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    # Tag a specific user at the top of the embed body
    tag_user_id = data.get("tag_user_id")
    if tag_user_id:
        embed.description = f"<@{tag_user_id}>\n\n{embed.description}"

    # Build ping line — sent as plain content alongside the embed so @everyone/@here fires
    ping_parts = []
    if data.get("tag_everyone"):
        ping_parts.append("@everyone")
    if data.get("tag_here"):
        ping_parts.append("@here")
    ping_content = " ".join(ping_parts) if ping_parts else None

    return embed, ping_content


async def ask_openai_text(channel_id: int, user_text: str, username: str) -> tuple[str, bool]:
    """Standard text reply via GPT-4o. Returns (reply_text, needs_support_redirect)."""
    msgs = get_channel_messages(channel_id)
    system_prompt = build_system_prompt()

    msgs.append({"role": "user", "content": f"{username}: {user_text}"})
    trim_history(channel_id)
    touch_channel(channel_id)

    response = client_ai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            *msgs,
        ],
        max_tokens=1024,
        temperature=0.7,
    )

    raw = response.choices[0].message.content.strip()

    # Check if bot flagged this as needing support
    needs_support = "---SUPPORT_REDIRECT---" in raw
    reply = raw.replace("---SUPPORT_REDIRECT---", "").strip()

    msgs.append({"role": "assistant", "content": reply})
    trim_history(channel_id)
    touch_channel(channel_id)
    save_history_to_disk()
    return reply, needs_support


async def ask_openai_with_image(channel_id: int, user_text: str, username: str, image_bytes: bytes, media_type: str) -> str:
    """Send image + text to GPT-4o vision and return reply."""
    msgs = get_channel_messages(channel_id)
    system_prompt = build_system_prompt()

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    vision_message = {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_type};base64,{image_b64}"
                }
            },
            {
                "type": "text",
                "text": f"{username}: {user_text}" if user_text else f"{username} sent this image."
            }
        ]
    }

    response = client_ai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            *msgs,
            vision_message,
        ],
        max_tokens=1024,
        temperature=0.7,
    )

    reply = response.choices[0].message.content.strip()
    msgs = get_channel_messages(channel_id)
    msgs.append({"role": "user", "content": f"{username}: [sent an image] {user_text}"})
    msgs.append({"role": "assistant", "content": reply})
    trim_history(channel_id)
    touch_channel(channel_id)
    save_history_to_disk()
    return reply


async def send_support_redirect(message: discord.Message):
    """Send a support channel redirect message tagging the support roles."""
    role_tags = " ".join([f"<@&{rid}>" for rid in SUPPORT_ROLES])
    await message.channel.send(
        f"🎫 Hey {message.author.mention}, it looks like this needs the attention of our support team!\n"
        f"Please head over to <#{SUPPORT_CHANNEL_ID}> and create a ticket — our staff will assist you there.\n"
        f"{role_tags}"
    )


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Transcribe audio using OpenAI Whisper."""
    ext = os.path.splitext(filename)[1].lower()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as audio_file:
            transcript = client_ai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return transcript.text
    finally:
        os.unlink(tmp_path)


# ── Server management helpers ────────────────────────────────────────────────
# Tracks pending delete confirmations: {original_message_id: channel_to_delete_id}
pending_deletions: dict[int, int] = {}

def has_admin_role(member: discord.Member) -> bool:
    """Check if member has one of the announcement/admin roles."""
    return any(role.id in ANNOUNCE_ROLES for role in member.roles)


def parse_role_command(text: str):
    """
    Detect give/remove role commands.
    Returns (action, user_id, role_id) or None.
    Examples:
      give @user the @role
      remove @role from @user
      give @user @role
    """
    action = None
    if re.search(r"\bgive\b|\badd\b|\bassign\b|\bgrant\b", text, re.IGNORECASE):
        action = "give"
    elif re.search(r"\bremove\b|\btake\b|\brevoke\b|\bstrip\b", text, re.IGNORECASE):
        action = "remove"

    if not action:
        return None

    user_match  = re.search(r"<@!?(\d+)>", text)
    role_match  = re.search(r"<@&(\d+)>", text)

    if not user_match or not role_match:
        return None

    return action, int(user_match.group(1)), int(role_match.group(1))


def parse_permission_command(text: str):
    """
    Detect permission edit commands.
    Returns (channel_or_cat_id, is_category, target_type, target_id, perm_name, allow) or None.
    Examples:
      lock <#channel>
      unlock <#channel>
      hide <#channel> from @role
      show <#channel> to @role
      deny send_messages in <#channel> for @role
      allow view_channel in <#channel> for @role
    """
    # Lock / unlock shortcuts
    if re.search(r"\block\b", text, re.IGNORECASE):
        ch = re.search(r"<#(\d+)>", text)
        if ch:
            return int(ch.group(1)), False, "everyone", None, "send_messages", False
    if re.search(r"\bunlock\b", text, re.IGNORECASE):
        ch = re.search(r"<#(\d+)>", text)
        if ch:
            return int(ch.group(1)), False, "everyone", None, "send_messages", True

    # Hide / show shortcuts
    if re.search(r"\bhide\b", text, re.IGNORECASE):
        ch = re.search(r"<#(\d+)>", text)
        role = re.search(r"<@&(\d+)>", text)
        if ch:
            return int(ch.group(1)), False, "role" if role else "everyone", int(role.group(1)) if role else None, "view_channel", False
    if re.search(r"\bshow\b|\bunhide\b", text, re.IGNORECASE):
        ch = re.search(r"<#(\d+)>", text)
        role = re.search(r"<@&(\d+)>", text)
        if ch:
            return int(ch.group(1)), False, "role" if role else "everyone", int(role.group(1)) if role else None, "view_channel", True

    return None


def parse_delete_command(text: str):
    """
    Detect delete channel commands.
    Returns channel_id or None.
    """
    if not re.search(r"\bdelete\b|\bremove channel\b", text, re.IGNORECASE):
        return None
    ch = re.search(r"<#(\d+)>", text)
    if ch:
        return int(ch.group(1))
    return None


def parse_purge_command(text: str):
    """
    Detect message purge/clear commands.
    Returns dict with keys: mode, channel_id, amount, keyword, user_id
    or None if not a purge command.

    Modes:
      count   — delete X messages
      keyword — delete messages containing a word/phrase
      user    — delete all messages from a specific user
      all     — delete ALL messages in the channel

    Examples:
      purge 50 messages in <#channel>
      clear 10 in <#channel>
      delete 20 messages in <#channel>
      purge messages containing "spam" in <#channel>
      clear messages from @user in <#channel>
      purge all messages in <#channel>
      purge all in <#channel>
    """
    if not re.search(
        r"\bpurge\b|\bclear\b|\bclean\b|\bwipe\b"
        r"|\bdelete\s+(the\s+)?(last\s+)?\d+\b"
        r"|\bdelete\s+all\b|\bdelete\s+messages\b"
        r"|\bremove\s+(the\s+)?(last\s+)?\d+\s+messages\b",
        text, re.IGNORECASE
    ):
        return None

    result = {
        "mode": None,
        "channel_id": None,
        "amount": None,
        "keyword": None,
        "user_id": None,
    }

    # Channel (optional — defaults to current channel if not specified)
    ch_match = re.search(r"<#(\d+)>", text)
    result["channel_id"] = int(ch_match.group(1)) if ch_match else None

    # Mode: ALL
    if re.search(r"\ball\b", text, re.IGNORECASE):
        result["mode"] = "all"
        return result

    # Mode: USER
    user_match = re.search(r"<@!?(\d+)>", text)
    if user_match and re.search(r"\bfrom\b|\bby\b", text, re.IGNORECASE):
        result["mode"] = "user"
        result["user_id"] = int(user_match.group(1))
        return result

    # Mode: KEYWORD
    kw_match = re.search(r'containing\s+"([^"]+)"', text, re.IGNORECASE)
    if not kw_match:
        kw_match = re.search(r"containing\s+'([^']+)'", text, re.IGNORECASE)
    if not kw_match:
        kw_match = re.search(r"containing\s+(\S+)", text, re.IGNORECASE)
    if not kw_match:
        kw_match = re.search(r"with\s+(?:the\s+word\s+)?[\"']?(\w+)[\"']?", text, re.IGNORECASE)
    if kw_match:
        result["mode"] = "keyword"
        result["keyword"] = kw_match.group(1)
        return result

    # Mode: COUNT — handles "delete 20", "delete the last 3", "clear last 50"
    num_match = re.search(r"(?:last\s+)?(\d+)", text, re.IGNORECASE)
    if num_match:
        result["mode"] = "count"
        result["amount"] = int(num_match.group(1))
        return result

    return None


def parse_create_command(text: str):
    """
    Detect create channel/category commands.
    Must have explicit "create" or "make" AND "channel", "category", or "voice channel"
    together — avoids false matches on normal messages.
    """
    # Must have a clear creation intent word
    if not re.search(r"\bcreate\b", text, re.IGNORECASE):
        # "make" only counts if directly followed by channel/category/voice
        if not re.search(r"\bmake\s+(a\s+)?(text\s+|voice\s+|private\s+)?channel\b|\bmake\s+(a\s+)?category\b", text, re.IGNORECASE):
            return None

    # Must explicitly mention channel or category
    if not re.search(r"\bchannel\b|\bcategory\b", text, re.IGNORECASE):
        return None

    result = {
        "type": "text",
        "name": None,
        "category_id": None,
        "private": False,
        "role_id": None,
    }

    if re.search(r"\bcategory\b", text, re.IGNORECASE):
        result["type"] = "category"
    elif re.search(r"\bvoice\b", text, re.IGNORECASE):
        result["type"] = "voice"
    else:
        result["type"] = "text"

    if re.search(r"\bprivate\b|\bsecret\b|\bhidden\b", text, re.IGNORECASE):
        result["private"] = True

    role_match = re.search(r"<@&(\d+)>", text)
    if role_match:
        result["role_id"] = int(role_match.group(1))

    cat_match = re.search(r"in\s+<#(\d+)>", text, re.IGNORECASE)
    if cat_match:
        result["category_id"] = int(cat_match.group(1))

    # Extract the name — strip command keywords
    name = text
    for pattern in [
        r"\bcreate\b", r"\bmake\b", r"\badd\b",
        r"\btext\b", r"\bvoice\b", r"\bcategory\b", r"\bchannel\b",
        r"\bprivate\b", r"\bsecret\b", r"\bhidden\b",
        r"\bfor\b", r"\bin\b", r"\bthe\b", r"\ba\b", r"\ban\b",
        r"<@&\d+>", r"<#\d+>",
    ]:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", "-", name.strip()).lower().strip("-")

    if not name:
        return None

    result["name"] = name
    return result


# ── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    # Ensure knowledge folder exists
    try:
        os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    except Exception as e:
        print(f"⚠️  Could not create knowledge folder: {e}")

    load_history_from_disk()
    purge_expired_history()
    bot.loop.create_task(auto_purge_loop())
    print(f"✅  AFC Bot is online as {bot.user} (id: {bot.user.id})")
    print(f"📌  Listening in {len(ALLOWED_CHANNELS)} channels")
    print(f"📚  Knowledge base loaded: {len(load_knowledge())} characters")
    print(f"🕒  Conversation history: saved to disk, auto-clears after 24 hours")


@bot.event
async def on_message(message: discord.Message):
    # Ignore bots entirely
    if message.author.bot:
        return
    try:
        await _handle_message(message)
    except Exception as e:
        print(f"⚠️  Unhandled error in on_message: {e}")


async def _handle_message(message: discord.Message):
    # Ignore self
    if message.author == bot.user:
        return

    # Only allowed channels
    if not is_allowed_channel(message.channel.id):
        return

    # Only respond when @mentioned
    if bot.user not in message.mentions:
        return

    # Strip the @mention
    user_text = message.content.replace(f"<@{bot.user.id}>", "").strip()
    username  = message.author.display_name

    # ── Announcement command ─────────────────────────────────────────────────
    announce = parse_announce_command(user_text)
    if announce:
        if not has_announce_role(message.author):
            await message.reply(
                "❌ You don't have permission to use the announcement command. Only AFC staff roles can do that.",
                mention_author=True
            )
            return

        target_channel_id, target_user_id, msg_content = announce
        target_channel = bot.get_channel(target_channel_id)

        if not target_channel:
            await message.reply("❌ I couldn't find that channel. Make sure I have access to it.", mention_author=True)
            return

        # Detect if admin wants AI to generate/formulate the announcement
        generate_keywords = [
            "formulate", "generate", "write", "create", "draft", "help me",
            "make", "compose", "craft", "prepare", "put together"
        ]
        should_generate = any(kw in user_text.lower() for kw in generate_keywords)

        async with message.channel.typing():
            if should_generate:
                await message.reply("✍️ Generating your announcement...", mention_author=True)
                try:
                    ann_data = await generate_announcement(msg_content, target_user_id)
                    embed, ping_content = build_embed(ann_data)
                    use_embed = True
                except Exception as e:
                    await message.reply(f"⚠️ Couldn't generate the announcement. Error: {e}", mention_author=True)
                    return
            else:
                # Plain send — if content is empty after stripping, ask what to send
                if not msg_content:
                    await message.reply(
                        "❓ What should I send? Please include the message content in your command.",
                        mention_author=True
                    )
                    return
                plain_text = f"<@{target_user_id}> {msg_content}" if target_user_id else msg_content
                embed = discord.Embed(description=plain_text, color=EMBED_COLORS["announcement"])
                embed.set_footer(text="African Freefire Community  •  africanfreefirecommunity.com")
                embed.timestamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                ping_content = None
                use_embed = True

        # Collect any attached media files to forward
        import io
        files_to_send = []
        if message.attachments:
            for attachment in message.attachments:
                file_bytes = await download_attachment(attachment)
                files_to_send.append(
                    discord.File(fp=io.BytesIO(file_bytes), filename=attachment.filename)
                )

        try:
            allowed = discord.AllowedMentions(everyone=True, roles=True, users=True)
            if files_to_send:
                await target_channel.send(
                    content=ping_content,
                    embed=embed,
                    files=files_to_send,
                    allowed_mentions=allowed
                )
            else:
                await target_channel.send(
                    content=ping_content,
                    embed=embed,
                    allowed_mentions=allowed
                )

            media_note = f" with {len(files_to_send)} file(s)" if files_to_send else ""
            await message.reply(f"✅ Announcement sent to <#{target_channel_id}>{media_note}.", mention_author=True)
        except discord.Forbidden:
            await message.reply(
                f"❌ I don't have permission to send messages in <#{target_channel_id}>. "
                "Make sure I have the Administrator role.",
                mention_author=True
            )
        return
    # ── End announcement ─────────────────────────────────────────────────────

    # ── Server management commands (admin only) ──────────────────────────────
    if has_admin_role(message.author):

        # ── Create channel / category ─────────────────────────────────────────
        create_cmd = parse_create_command(user_text)
        if create_cmd:
            guild     = message.guild
            ch_type   = create_cmd["type"]
            ch_name   = create_cmd["name"]
            is_private = create_cmd["private"]
            role_id   = create_cmd["role_id"]
            cat_id    = create_cmd["category_id"]

            # Resolve category if given
            category = None
            if cat_id:
                category = guild.get_channel(cat_id)
                if category and not isinstance(category, discord.CategoryChannel):
                    category = None  # not actually a category

            try:
                overwrites = {}

                if is_private:
                    # Hide from everyone by default
                    overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                    # Give access to the specified role if provided
                    if role_id:
                        role = guild.get_role(role_id)
                        if role:
                            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                    # Always give access to admin roles
                    for admin_role_id in ANNOUNCE_ROLES:
                        admin_role = guild.get_role(admin_role_id)
                        if admin_role:
                            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

                if ch_type == "category":
                    new_ch = await guild.create_category(
                        name=ch_name,
                        overwrites=overwrites if overwrites else None,
                        reason=f"AFC Bot — created by {message.author}"
                    )
                    ch_label = f"📁 Category **{new_ch.name}**"

                elif ch_type == "voice":
                    new_ch = await guild.create_voice_channel(
                        name=ch_name,
                        category=category,
                        overwrites=overwrites if overwrites else None,
                        reason=f"AFC Bot — created by {message.author}"
                    )
                    ch_label = f"🔊 Voice channel **{new_ch.name}**"

                else:  # text
                    new_ch = await guild.create_text_channel(
                        name=ch_name,
                        category=category,
                        overwrites=overwrites if overwrites else None,
                        reason=f"AFC Bot — created by {message.author}"
                    )
                    ch_label = f"💬 Channel {new_ch.mention}"

                # Build response embed
                desc = f"✅ {ch_label} has been created."
                if category and ch_type != "category":
                    desc += f"\n📁 Category: **{category.name}**"
                if is_private:
                    desc += f"\n🔒 **Private** — hidden from @everyone"
                    if role_id:
                        desc += f" | Accessible to <@&{role_id}>"

                embed = discord.Embed(description=desc, color=EMBED_COLORS["general"])
                embed.set_footer(text=f"Created by {message.author.display_name}")
                await message.reply(embed=embed, mention_author=True)

            except discord.Forbidden:
                await message.reply("❌ I don't have permission to create channels. Make sure I have the Administrator role.", mention_author=True)
            return

        # ── Give / Remove role ───────────────────────────────────────────────
        role_cmd = parse_role_command(user_text)
        if role_cmd:
            action, target_user_id, target_role_id = role_cmd
            guild = message.guild
            member = guild.get_member(target_user_id)
            role   = guild.get_role(target_role_id)

            if not member:
                await message.reply("❌ Couldn't find that user in this server.", mention_author=True)
                return
            if not role:
                await message.reply("❌ Couldn't find that role.", mention_author=True)
                return

            try:
                if action == "give":
                    await member.add_roles(role, reason=f"AFC Bot — assigned by {message.author}")
                    embed = discord.Embed(
                        description=f"✅ **{role.name}** has been given to {member.mention}.",
                        color=EMBED_COLORS["general"]
                    )
                else:
                    await member.remove_roles(role, reason=f"AFC Bot — removed by {message.author}")
                    embed = discord.Embed(
                        description=f"✅ **{role.name}** has been removed from {member.mention}.",
                        color=EMBED_COLORS["urgent"]
                    )
                embed.set_footer(text=f"Action by {message.author.display_name}")
                await message.reply(embed=embed, mention_author=True)
            except discord.Forbidden:
                await message.reply("❌ I don't have permission to manage that role. Make sure my role is above it in the role list.", mention_author=True)
            return

        # ── Edit channel / category permissions ──────────────────────────────
        perm_cmd = parse_permission_command(user_text)
        if perm_cmd:
            ch_id, is_category, target_type, target_role_id, perm_name, allow = perm_cmd
            guild   = message.guild
            channel = guild.get_channel(ch_id)

            if not channel:
                await message.reply("❌ Couldn't find that channel.", mention_author=True)
                return

            # Determine the target (a role or @everyone)
            if target_type == "role" and target_role_id:
                target = guild.get_role(target_role_id)
                target_label = f"@{target.name}" if target else "that role"
            else:
                target = guild.default_role   # @everyone
                target_label = "@everyone"

            if not target:
                await message.reply("❌ Couldn't find that role.", mention_author=True)
                return

            try:
                perm_overwrite = channel.overwrites_for(target)
                setattr(perm_overwrite, perm_name, allow if allow else None)
                await channel.set_permissions(target, overwrite=perm_overwrite, reason=f"AFC Bot — changed by {message.author}")

                action_word = "allowed" if allow else "denied/removed"
                perm_display = perm_name.replace("_", " ").title()
                embed = discord.Embed(
                    description=f"✅ **{perm_display}** {action_word} for **{target_label}** in {channel.mention}.",
                    color=EMBED_COLORS["general"]
                )
                embed.set_footer(text=f"Action by {message.author.display_name}")
                await message.reply(embed=embed, mention_author=True)
            except discord.Forbidden:
                await message.reply("❌ I don't have permission to edit that channel's permissions.", mention_author=True)
            return

        # ── Delete channel (with confirmation) ───────────────────────────────
        del_cmd = parse_delete_command(user_text)
        if del_cmd:
            target_ch = message.guild.get_channel(del_cmd)
            if not target_ch:
                await message.reply("❌ Couldn't find that channel.", mention_author=True)
                return

            # Store pending and ask for confirmation
            pending_deletions[message.id] = del_cmd
            embed = discord.Embed(
                title="⚠️ Confirm Channel Deletion",
                description=(
                    f"You are about to permanently delete **{target_ch.name}**.\n\n"
                    f"**This cannot be undone.**\n\n"
                    f"Reply with ✅ `yes` or ❌ `no` to confirm."
                ),
                color=EMBED_COLORS["urgent"]
            )
            embed.set_footer(text=f"Requested by {message.author.display_name} • Expires in 30 seconds")
            confirm_msg = await message.reply(embed=embed, mention_author=True)

            # Wait for confirmation
            def check(m):
                return (
                    m.author.id == message.author.id
                    and m.channel.id == message.channel.id
                    and m.content.lower().strip() in ("yes", "no", "y", "n")
                )

            try:
                reply_msg = await bot.wait_for("message", check=check, timeout=30.0)
                if reply_msg.content.lower().strip() in ("yes", "y"):
                    ch_name = target_ch.name
                    await target_ch.delete(reason=f"AFC Bot — deleted by {message.author}")
                    embed2 = discord.Embed(
                        description=f"🗑️ Channel **#{ch_name}** has been deleted.",
                        color=EMBED_COLORS["urgent"]
                    )
                    embed2.set_footer(text=f"Action by {message.author.display_name}")
                    await message.channel.send(embed=embed2)
                else:
                    await message.channel.send("❌ Channel deletion cancelled.")
            except asyncio.TimeoutError:
                await message.channel.send("⏱️ Confirmation timed out. Channel deletion cancelled.")
            finally:
                pending_deletions.pop(message.id, None)
            return

        # ── Purge messages ────────────────────────────────────────────────────
        purge_cmd = parse_purge_command(user_text)
        if purge_cmd:
            mode       = purge_cmd["mode"]
            target_cid = purge_cmd["channel_id"] or message.channel.id
            amount     = purge_cmd["amount"]
            keyword    = purge_cmd["keyword"]
            pu_user_id = purge_cmd["user_id"]
            guild      = message.guild
            target_ch  = guild.get_channel(target_cid) or message.channel

            # Build confirmation embed
            if mode == "count":
                summary = f"Delete the last **{amount}** messages in {target_ch.mention}"
            elif mode == "keyword":
                summary = f"Delete all messages containing **\"{keyword}\"** in {target_ch.mention}"
            elif mode == "user":
                summary = f"Delete all messages from <@{pu_user_id}> in {target_ch.mention}"
            elif mode == "all":
                summary = f"Delete **ALL** messages in {target_ch.mention} — no matter how old"
            else:
                await message.reply("❌ Couldn't understand that purge command.", mention_author=True)
                return

            embed = discord.Embed(
                title="⚠️ Confirm Message Purge",
                description=f"{summary}\n\n**This cannot be undone.**\n\nReply `yes` to confirm or `no` to cancel.",
                color=EMBED_COLORS["urgent"]
            )
            embed.set_footer(text=f"Requested by {message.author.display_name} • Expires in 30 seconds")
            await message.reply(embed=embed, mention_author=True)

            def purge_check(m):
                return (
                    m.author.id == message.author.id
                    and m.channel.id == message.channel.id
                    and m.content.lower().strip() in ("yes", "no", "y", "n")
                )

            try:
                confirm = await bot.wait_for("message", check=purge_check, timeout=30.0)
                if confirm.content.lower().strip() not in ("yes", "y"):
                    await message.channel.send("❌ Purge cancelled.")
                    return
            except asyncio.TimeoutError:
                await message.channel.send("⏱️ Confirmation timed out. Purge cancelled.")
                return

            # Execute the purge in a background task so the bot stays responsive
            async def do_purge():
                deleted_count = 0

                async def safe_delete(msg):
                    """Delete one message with rate-limit retry."""
                    for _ in range(5):
                        try:
                            await msg.delete()
                            return True
                        except discord.HTTPException as e:
                            if e.status == 429:
                                wait = getattr(e, "retry_after", 2.0) or 2.0
                                await asyncio.sleep(float(wait) + 0.5)
                            elif e.status == 404:
                                return True   # already deleted
                            else:
                                return False
                        except Exception:
                            return False
                    return False

                try:
                    if mode == "count":
                        deleted = await target_ch.purge(limit=amount)
                        deleted_count = len(deleted)

                    elif mode == "keyword":
                        def kw_check(m): return keyword.lower() in m.content.lower()
                        deleted = await target_ch.purge(limit=None, check=kw_check)
                        deleted_count = len(deleted)
                        async for old_msg in target_ch.history(limit=None):
                            if keyword.lower() in old_msg.content.lower():
                                if await safe_delete(old_msg):
                                    deleted_count += 1
                                    await asyncio.sleep(1.2)

                    elif mode == "user":
                        def user_check(m): return m.author.id == pu_user_id
                        deleted = await target_ch.purge(limit=None, check=user_check)
                        deleted_count = len(deleted)
                        async for old_msg in target_ch.history(limit=None):
                            if old_msg.author.id == pu_user_id:
                                if await safe_delete(old_msg):
                                    deleted_count += 1
                                    await asyncio.sleep(1.2)

                    elif mode == "all":
                        deleted = await target_ch.purge(limit=None)
                        deleted_count = len(deleted)
                        async for old_msg in target_ch.history(limit=None):
                            if await safe_delete(old_msg):
                                deleted_count += 1
                                await asyncio.sleep(1.2)

                    result_embed = discord.Embed(
                        description=f"✅ **{deleted_count}** message(s) deleted from {target_ch.mention}.",
                        color=EMBED_COLORS["general"]
                    )
                    result_embed.set_footer(text=f"Action by {message.author.display_name}")
                    await message.channel.send(embed=result_embed)

                except discord.Forbidden:
                    await message.channel.send("❌ I don't have permission to delete messages in that channel.")
                except Exception as e:
                    await message.channel.send(f"⚠️ Something went wrong during purge: {e}")

            asyncio.ensure_future(do_purge())
            return

    # ── End server management ─────────────────────────────────────────────────

    # ── Handle attachments ───────────────────────────────────────────────────
    if message.attachments:
        async with message.channel.typing():
            attachment = message.attachments[0]
            att_type   = get_attachment_type(attachment.filename)

            # 🖼️ IMAGE — GPT-4o Vision
            if att_type == "image":
                try:
                    image_bytes = await download_attachment(attachment)
                    ext = os.path.splitext(attachment.filename)[1].lower().strip(".")
                    media_type_map = {
                        "jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "png": "image/png", "gif": "image/gif", "webp": "image/webp"
                    }
                    media_type = media_type_map.get(ext, "image/jpeg")
                    prompt = user_text if user_text else "What is in this image? Give context relevant to AFC or Free Fire if applicable."
                    reply  = await ask_openai_with_image(message.channel.id, prompt, username, image_bytes, media_type)
                    await message.reply(reply, mention_author=True)
                except Exception as e:
                    await message.reply(f"⚠️ I couldn't analyze that image. Error: {e}", mention_author=True)
                return

            # 🎵 AUDIO — Whisper transcription → GPT-4o reply
            elif att_type == "audio":
                try:
                    await message.reply("🎵 Got your audio! Give me a sec to listen...", mention_author=True)
                    audio_bytes = await download_attachment(attachment)
                    transcript  = await transcribe_audio(audio_bytes, attachment.filename)

                    if not transcript.strip():
                        await message.reply("⚠️ I couldn't make out what was said. Try sending a clearer recording.", mention_author=True)
                        return

                    combined = f"[Audio message transcribed]: {transcript}"
                    if user_text:
                        combined += f"\n[User also typed]: {user_text}"

                    reply, needs_support = await ask_openai_text(message.channel.id, combined, username)
                    await message.reply(f"🎙️ **I heard:** _{transcript}_\n\n{reply}", mention_author=True)
                    if needs_support:
                        await send_support_redirect(message)
                except Exception as e:
                    await message.reply(f"⚠️ I couldn't transcribe that audio. Error: {e}", mention_author=True)
                return

            # 🎥 VIDEO — Acknowledge, can't analyze
            elif att_type == "video":
                context = f"{username} sent a video called '{attachment.filename}'. " \
                          f"Acknowledge you received it but explain warmly that you can't watch or analyze videos yet. " \
                          f"They also said: '{user_text}'. Reply naturally and in character as AFC Bot."
                reply, needs_support = await ask_openai_text(message.channel.id, context, username)
                await message.reply(reply, mention_author=True)
                if needs_support:
                    await send_support_redirect(message)
                return

            # ❓ Unknown file type
            else:
                reply, needs_support = await ask_openai_text(
                    message.channel.id,
                    f"{username} sent a file called '{attachment.filename}'. {user_text}",
                    username
                )
                await message.reply(reply, mention_author=True)
                if needs_support:
                    await send_support_redirect(message)
                return

    # ── Standard text reply ──────────────────────────────────────────────────
    if not user_text:
        user_text = "Hello!"

    reply_context = await get_reply_context(message)
    if reply_context:
        user_text = reply_context + user_text

    async with message.channel.typing():
        try:
            reply, needs_support = await ask_openai_text(message.channel.id, user_text, username)
        except Exception as exc:
            reply = f"⚠️ Something went wrong. Please try again or contact info@africanfreefirecommunity.com\nError: {exc}"
            needs_support = False

    await message.reply(reply, mention_author=True)
    if needs_support:
        await send_support_redirect(message)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
