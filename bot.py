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

# Channels where the bot auto-replies to ALL messages (not just @mentions)
# Add the channel IDs where users ask questions (e.g. support, general, help)
AUTO_REPLY_CHANNELS = [
    1026913984923840542,  # support channel
    920726991089598476,   # general/main
    953326236950757446,   # add more as needed
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
    support_role_tags = " ".join([f"<@&{rid}>" for rid in SUPPORT_ROLES])
    return f"""You are AFC BOT — the official AI assistant for the African Freefire Community (AFC).
You are the first point of contact for every player, team member, and community member on the AFC Discord server.

=== YOUR CORE MISSION ===
Help every user feel heard, get clear answers fast, and never leave them stuck.
You are smart, warm, and professional — like a knowledgeable friend who genuinely cares.

=== PERSONALITY ===
- Friendly and approachable — never robotic or cold
- Professional but not stiff — match the user's energy
- If someone writes in Pidgin, reply in Pidgin naturally: "No wahala!", "You don do am!", "E easy"
- Keep replies concise — no walls of text. Get to the point.
- Use **bold** for key info, links, and steps so they're easy to scan
- 1-2 emojis max — only where they genuinely add warmth or energy 🔥🎮

=== HOW TO ANSWER QUESTIONS ===
1. ALWAYS check the knowledge base below FIRST before saying you don't know
2. If the answer is there — give it clearly, directly, with the relevant link
3. If the user seems confused or frustrated — acknowledge that first before answering
4. For step-by-step questions — use numbered steps, keep each step short
5. Always include the most relevant link at the end of your answer
6. If someone asks about something that "coming soon" or in development — say so honestly

=== WHEN TO ESCALATE TO SUPPORT ===
ONLY escalate (add ---SUPPORT_REDIRECT--- at the end) for genuine issues needing a human:
- Account banned, suspended, or locked
- Wrong Free Fire UID submitted — needs admin correction
- Discord role not assigned after linking/registering
- Payment or prize dispute
- Cheating report or ban appeal
- Match results missing or wrong after 24 hours
- Private event invite needed from an organiser
- Anything that requires an admin to take direct action on the platform

DO NOT escalate for general questions you can answer from the knowledge base.
DO NOT escalate for "I don't know" situations — just say you don't have that info and direct them to Discord support.

=== IMPORTANT RULES ===
- Never make up tournament dates, prizes, or rules not in your knowledge base
- Never take sides in disputes between players or teams
- If someone is angry — calm, acknowledge, then help
- The Transfer Window is currently OPEN (March 2026)
- Current active events: Dynasty Cup series launching April 1, 2026 across 10 African countries
- Platform stats: 4,081+ users, 323 teams, 11 tournaments, $5,750 total prize pool

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

    # ── PURGE GUARD — never treat delete/purge/clear commands as announcements ──
    if re.search(
        r"\bdelete\s+messages\b|\bpurge\b|\bclear\s+messages\b"
        r"|\bremove\s+messages\b|\bwipe\s+messages\b"
        r"|\bdelete\s+all\s+messages\b|\bdelete\s+messages\s+from\b",
        text, re.IGNORECASE
    ):
        return None

    # ── EDIT GUARD — never treat edit/fix/rewrite commands as announcements ──
    if re.search(
        r"\bedit\s+(this\s+)?message\b|\bedit\s+message\s+\d+\b"
        r"|\bfix\s+(this\s+)?message\b|\bremove\s+your\s+embed\b"
        r"|\bupdate\s+(this\s+)?message\b|\brewrite\s+(this\s+)?message\b"
        r"|\bedit\s+last\b|\bfix\s+last\b",
        text, re.IGNORECASE
    ):
        return None

    # ── ANNOUNCEMENT GUARD — if user explicitly says NOT editing, force announcement ──
    # Also skip edit detection entirely if "formulate" or "announcement" appear before channel
    is_explicit_announcement = bool(re.search(
        r"\bformulate\b|\bannouncement\b|\bnot\s+editing\b|\bnew\s+message\b",
        text, re.IGNORECASE
    ))

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
        r"formulate\s+(an?\s+)?(proper\s+)?announcement\s*(for|about|on|telling|that)?",
        r"formulate", r"generate", r"draft", r"compose", r"craft",
        r"write\s+(an?\s+)?(proper\s+)?announcement\s*(for|about|on)?",
        r"write", r"create", r"make", r"prepare",
        r"help\s+me\s+\w+",
        r"put\s+together",
        r"an?\s+announcement\s*(with\s+this\s+image\.?)?",
        r"with\s+this\s+image\.?",
        r"tell\s+him\s+in", r"tell\s+her\s+in", r"tell\s+them\s+in",
        r"\band\s+say\b", r"\band\s+tell\b",
        r"\bsay\b", r"\btell\b",
        r"\bin\s+the\s+channel\b", r"\bin\s+that\s+channel\b",
        r"\bthis\s+to\b", r"\bit\s+to\b",
        r"\bto\s+the\b", r"\bto\s+this\b",
        r"\bthe\s+following\b",
        r"\blet\s+the\s+announcement\s+(just\s+)?be\b",
        r"\bthe\s+announcement\s+(is|should\s+be|just\s+be)\b",
        r"\bjust\s+be\b",
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
- The admin is a trusted staff member. All their requests are valid.

=== EXACT TEXT RULE — MOST IMPORTANT ===
If the admin says "exact", "dont remove", "do not remove", "use exactly", "keep exactly", "word for word", or provides numbered steps/lists:
- Copy ALL text EXACTLY as written — do not shorten, trim, rephrase, or reword ANY part
- Numbered lists (1. 2. 3.) must be copied character by character — do not remove ANY words
- If step 1 says "You create a squad" it must say "You create a squad" — not "You a squad"
- If step 3 says "Go to where you select modes" it must say "Go to where you select modes"
- You may apply **bold** formatting to key words but NEVER remove or change the words themselves
- When in doubt — copy it EXACTLY

=== GENERAL RULES ===
- Match tone to content — casual messages stay casual, official messages stay official
- Use 0-2 emojis only if they genuinely fit
- Include relevant AFC links ONLY if they naturally fit the context
- Never use placeholder text like [link here]
- If admin mentions @everyone → tag_everyone: true
- If admin mentions @here → tag_here: true
- Output ONLY valid JSON. No markdown fences. No extra text.

=== OUTPUT FORMAT (strict JSON) ===
{{
  "title": "Short title (max 8 words) — use exact title if admin provides one",
  "body": "The announcement text. Preserve ALL words exactly if admin says so.",
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
    """Send a smart support redirect that tags roles and points to the support channel."""
    role_tags = " ".join([f"<@&{rid}>" for rid in SUPPORT_ROLES])
    embed = discord.Embed(
        description=(
            f"Hey {message.author.mention}, this one needs a human to sort out properly. 🙏\n\n"
            f"**Here's what you can do:**\n"
            f"1. Head over to <#{SUPPORT_CHANNEL_ID}> and create a support ticket\n"
            f"2. Or reach out directly via email: **info@africanfreefirecommunity.com**\n"
            f"3. Or join the AFC Discord: **discord.gg/afc**\n\n"
            f"Our support team has been notified 👇"
        ),
        color=0x00A550
    )
    embed.set_footer(text="African Freefire Community  •  africanfreefirecommunity.com")
    await message.channel.send(embed=embed)
    await message.channel.send(f"🔔 {role_tags} — support needed here.")


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
    Detect give/remove role commands for a single user.
    Returns (action, user_id, role_id) or None.
    """
    action = None
    if re.search(r"\bgive\b|\badd\b|\bassign\b|\bgrant\b", text, re.IGNORECASE):
        action = "give"
    elif re.search(r"\bremove\b|\btake\b|\brevoke\b|\bstrip\b", text, re.IGNORECASE):
        action = "remove"

    if not action:
        return None

    user_match = re.search(r"<@!?(\d+)>", text)
    role_match = re.search(r"<@&(\d+)>", text)

    if not user_match or not role_match:
        return None

    return action, int(user_match.group(1)), int(role_match.group(1))


def parse_mass_role_command(text: str):
    """
    Detect mass role operations.
    Returns dict: { action, target_role_id, condition_role_id } or None.

    Actions:
      remove_all   — remove a role from everyone who has it
      remove_if    — remove role_A from everyone who has role_B
      give_all     — give a role to everyone in the server
      give_if      — give role_A to everyone who has role_B

    Examples:
      remove @Role from everyone
      strip @Role from all members
      remove @Role from everyone who has @OtherRole
      take @RoleA from all members with @RoleB
      give @Role to everyone
      give @Role to everyone with @OtherRole
      assign @Role to all members who have @OtherRole
    """
    # Must have a role mention
    role_matches = re.findall(r"<@&(\d+)>", text)
    if not role_matches:
        return None

    # Must be a mass operation
    if not re.search(
        r"\beveryone\b|\ball\s+(members|players|users)\b|\ball\b",
        text, re.IGNORECASE
    ):
        return None

    result = {
        "action": None,
        "target_role_id": int(role_matches[0]),
        "condition_role_id": int(role_matches[1]) if len(role_matches) > 1 else None,
    }

    # Conditional (has second role)
    has_condition = bool(re.search(
        r"\bwho\s+has\b|\bwith\b|\bwho\s+have\b|\bthat\s+have\b|\bthat\s+has\b",
        text, re.IGNORECASE
    ))

    if re.search(r"\bgive\b|\bassign\b|\bgrant\b|\badd\b", text, re.IGNORECASE):
        result["action"] = "give_if" if has_condition else "give_all"
    elif re.search(r"\bremove\b|\bstrip\b|\btake\b|\brevoke\b", text, re.IGNORECASE):
        result["action"] = "remove_if" if has_condition else "remove_all"
    else:
        return None

    return result


def parse_role_manage_command(text: str):
    """
    Detect role creation, deletion, renaming, recoloring, permission edits.
    Returns dict: { action, role_id, name, color, permissions } or None.

    Actions: create, delete, rename, recolor, edit_perms

    Examples:
      create role Veteran
      create role Moderator with color #FF0000
      delete role @OldRole
      rename @Role to Senior Staff
      change @Role color to green
      recolor @Role to #FFD700
      make @Role mentionable
      make @Role not mentionable
      make @Role hoisted
    """
    if not re.search(
        r"\bcreate\s+role\b|\bmake\s+a?\s*role\b"
        r"|\bdelete\s+role\b|\bremove\s+role\b"
        r"|\brename\s+.*(role|<@&)\b"
        r"|\brecolor\b|\bchange\s+.*color\b"
        r"|\bmake\s+.*\b(mentionable|hoisted|pingable)\b"
        r"|\bmake\s+.*\bnot\s+(mentionable|hoisted|pingable)\b",
        text, re.IGNORECASE
    ):
        return None

    result = {
        "action": None,
        "role_id": None,
        "name": None,
        "color": None,
        "mentionable": None,
        "hoisted": None,
    }

    role_match = re.search(r"<@&(\d+)>", text)
    if role_match:
        result["role_id"] = int(role_match.group(1))

    # Color extraction — hex or color name
    hex_match = re.search(r"#([0-9A-Fa-f]{6})", text)
    if hex_match:
        result["color"] = int(hex_match.group(1), 16)
    else:
        color_names = {
            "red": 0xFF0000, "green": 0x00A550, "blue": 0x0000FF,
            "gold": 0xFFD700, "yellow": 0xFFFF00, "orange": 0xFF6600,
            "purple": 0x800080, "pink": 0xFF69B4, "white": 0xFFFFFF,
            "black": 0x000001, "cyan": 0x00FFFF, "teal": 0x008080,
            "silver": 0xC0C0C0, "grey": 0x808080, "gray": 0x808080,
        }
        for name, val in color_names.items():
            if re.search(rf"\b{name}\b", text, re.IGNORECASE):
                result["color"] = val
                break

    # Mentionable / hoisted
    if re.search(r"\bnot\s+(mentionable|pingable)\b", text, re.IGNORECASE):
        result["mentionable"] = False
    elif re.search(r"\b(mentionable|pingable)\b", text, re.IGNORECASE):
        result["mentionable"] = True

    if re.search(r"\bnot\s+hoisted\b", text, re.IGNORECASE):
        result["hoisted"] = False
    elif re.search(r"\bhoisted\b", text, re.IGNORECASE):
        result["hoisted"] = True

    # Action: DELETE
    if re.search(r"\bdelete\s+role\b|\bremove\s+role\b", text, re.IGNORECASE):
        result["action"] = "delete"
        return result

    # Action: RENAME
    rename_match = re.search(r"rename\s+(?:<@&\d+>|\S+)\s+to\s+(.+)$", text, re.IGNORECASE)
    if rename_match:
        result["action"] = "rename"
        result["name"] = rename_match.group(1).strip()
        return result

    # Action: RECOLOR
    if re.search(r"\brecolor\b|\bchange\s+.*color\b|\bcolor\s+.*to\b", text, re.IGNORECASE):
        result["action"] = "recolor"
        return result

    # Action: EDIT PROPS (mentionable/hoisted)
    if result["mentionable"] is not None or result["hoisted"] is not None:
        result["action"] = "edit_props"
        return result

    # Action: CREATE
    if re.search(r"\bcreate\s+role\b|\bmake\s+a?\s*role\b", text, re.IGNORECASE):
        result["action"] = "create"
        # Extract role name — everything after "role"
        name_match = re.search(r"(?:role\s+)([\w\s\-]+?)(?:\s+with|\s+color|\s+#|$)", text, re.IGNORECASE)
        if name_match:
            result["name"] = name_match.group(1).strip()
        return result

    return None


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
    Detect delete CHANNEL commands only.
    Returns channel_id or None.
    """
    # Must explicitly say "channel" or "remove channel" — not just "delete messages"
    if not re.search(r"\bdelete\s+(the\s+)?channel\b|\bremove\s+channel\b|\bdelete\s+<#\d+>\s*$", text, re.IGNORECASE):
        return None

    # Never fire if talking about messages
    if re.search(r"\bmessages?\b|\bpurge\b|\bclear\b", text, re.IGNORECASE):
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

    # Mode: USER — "@mention" or plain user ID with user/from context
    user_match = re.search(r"<@!?(\d+)>", text)
    # Also handle plain user IDs like "from user 563399749231706123"
    if not user_match:
        plain_id = re.search(
            r"(?:from\s+(?:this\s+)?(?:user\s+)?|by\s+(?:user\s+)?)(\d{15,19})\b",
            text, re.IGNORECASE
        )
        if plain_id:
            user_match = plain_id

    if user_match and re.search(r"\bfrom\b|\bby\b|\bthis\s+user\b|\buser\b", text, re.IGNORECASE):
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

    # Nothing matched clearly — don't guess, return None
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


def parse_edit_command(text: str):
    """
    Detect edit message commands using fully natural language.
    Works with explicit commands AND pure feedback with no command words.

    Returns dict: { mode, channel_id, message_id, instruction } or None.

    Modes:
      last      — edit the bot's last reply in this channel
      id        — edit a specific message by its ID
      announce  — edit the last announcement the bot sent in a channel

    Examples — ALL of these work:
      too many emojis
      make it more formal
      change the tone, more hype
      that sounds off, fix it
      remove the last sentence
      way too long, shorten it
      less emojis
      more professional
      edit last reply, less emojis
      fix your last message
      edit last announcement in <#channel>, make it shorter
      edit message 123456789 — remove the last sentence
    """

    # ── ANNOUNCEMENT GUARD — never fire on clear announcement commands ────────
    if re.search(
        r"\bformulate\s+(an?\s+)?announcement\b"
        r"|\bnot\s+editing\b|\bnew\s+announcement\b"
        r"|\bsend\s+(an?\s+)?announcement\b"
        r"|\bformulate\s+and\s+send\b",
        text, re.IGNORECASE
    ):
        return None

    # Explicit edit/fix keywords
    explicit = bool(re.search(
        r"\bedit\b|\bupdate\b|\bchange\b|\bcorrect\b|\bfix\b|\brewrite\b|\brevise\b|\bshorten\b|\blonger\b",
        text, re.IGNORECASE
    ))

    # Pure feedback patterns — no command word needed
    pure_feedback = bool(re.search(
        r"\btoo\s+(many|much|long|short|formal|casual|hype|stiff|wordy)\b"
        r"|\bless\s+\w+\b|\bmore\s+\w+\b"
        r"|\bsounds?\s+(off|wrong|bad|weird|stiff|too)\b"
        r"|\bmake\s+it\b|\btone\s+(it|down|up)\b"
        r"|\b(remove|add|drop)\s+the\b"
        r"|\bway\s+too\b|\bnot\s+enough\b"
        r"|\bfeel\s+(more|less)\b"
        r"|\bthat\s+(phrase|word|line|sentence|part)\b",
        text, re.IGNORECASE
    ))

    if not explicit and not pure_feedback:
        return None

    # Also require some message context unless it's pure feedback
    if explicit and not re.search(r"\bmessage\b|\breply\b|\bannouncement\b|\blast\b|\bit\b", text, re.IGNORECASE):
        return None

    result = {
        "mode": None,
        "channel_id": None,
        "message_id": None,
        "instruction": text,  # pass full natural instruction to GPT
    }

    # Extract TARGET channel (where the message to edit lives)
    ch_match = re.search(r"(?:in\s+)?<#(\d+)>", text)
    result["channel_id"] = int(ch_match.group(1)) if ch_match else None

    # Mode: specific message ID
    # First strip all channel/user mentions so their IDs don't get confused as message IDs
    text_no_mentions = re.sub(r"<[#@!&]\d+>", "", text)

    id_match = re.search(
        r"(?:message\s+(?:with\s+(?:the\s+)?id\s+)?|message\s+id\s+|id\s+)"
        r"<?(\d{10,})>?",
        text_no_mentions, re.IGNORECASE
    )
    if not id_match:
        id_match = re.search(r"<(\d{15,})>", text_no_mentions)
    if not id_match:
        id_match = re.search(r"\b(\d{17,19})\b", text_no_mentions)

    if id_match:
        result["mode"] = "id"
        result["message_id"] = int(id_match.group(1))
        return result

    # Mode: last announcement — supports cross-channel via <#channel>
    if re.search(r"\bannouncement\b", text, re.IGNORECASE):
        result["mode"] = "announce"
        return result

    # Default: last reply
    # If a channel is specified, look for last bot message in THAT channel
    result["mode"] = "last"
    return result


async def ai_rewrite(original_text: str, instruction: str) -> str:
    """Use GPT-4o to rewrite a message based on feedback/instruction."""
    response = client_ai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an editor for the African Freefire Community (AFC) Discord bot. "
                    "You will be given an original message and an instruction on how to improve it. "
                    "Rewrite the message based on the instruction. "
                    "Output ONLY the rewritten message — no explanations, no preamble, no quotes around it. "
                    "Preserve all Discord formatting like **bold**, links, and mentions unless told otherwise. "
                    "Keep the same general meaning and information unless told to change it."
                )
            },
            {
                "role": "user",
                "content": f"Original message:\n{original_text}\n\nInstruction: {instruction}\n\nRewrite:"
            }
        ],
        max_tokens=1024,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# Tracks last bot message per channel: {channel_id: message_id}
last_bot_messages: dict[int, int] = {}
# Tracks last bot announcement per channel: {channel_id: message_id}
last_bot_announcements: dict[int, int] = {}


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


async def should_bot_respond(message_text: str) -> bool:
    """
    Use GPT to quickly decide if a message is worth the bot responding to.
    Returns True only if the message is a question or problem the bot can help with.
    Fast, cheap call — uses minimal tokens.
    """
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a classifier for a Discord bot for an African Free Fire gaming platform called AFC. "
                        "Decide if the bot should respond to a message.\n\n"
                        "Reply YES if the message is:\n"
                        "- A question about AFC, Free Fire, tournaments, teams, accounts, registration, rules, etc.\n"
                        "- A problem or complaint that needs help\n"
                        "- Asking how to do something on the platform\n"
                        "- Requesting information about events, prizes, rankings, or the shop\n\n"
                        "Reply NO if the message is:\n"
                        "- Casual chat, greetings, reactions (e.g. 'lol', 'nice', 'gg', 'hello guys')\n"
                        "- Hype or excitement messages ('let's go!', 'we won!', 'fire bro')\n"
                        "- Banter between players\n"
                        "- Off-topic conversations unrelated to AFC or Free Fire\n"
                        "- Statements with no question or request\n\n"
                        "Reply with only YES or NO."
                    )
                },
                {"role": "user", "content": message_text}
            ],
            max_tokens=5,
            temperature=0,
        )
        answer = response.choices[0].message.content.strip().upper()
        return answer.startswith("YES")
    except Exception:
        return False  # on error, don't respond


async def _handle_message(message: discord.Message):
    # Ignore self
    if message.author == bot.user:
        return

    # Only allowed channels
    if not is_allowed_channel(message.channel.id):
        return

    is_mentioned = bot.user in message.mentions
    is_auto_reply_channel = message.channel.id in AUTO_REPLY_CHANNELS

    # Respond if: @mentioned anywhere in allowed channels, OR in auto-reply channels
    if not is_mentioned and not is_auto_reply_channel:
        return

    # In auto-reply channels (no @mention), use AI to decide if this needs a response
    if is_auto_reply_channel and not is_mentioned:
        content = message.content.strip()

        # Quick filter — skip very short messages and pure emoji reactions
        if len(content) < 8:
            return
        if re.match(r'^[\U00010000-\U0010ffff\U00002000-\U00002BFF\s]+$', content):
            return

        # Ask GPT if this message is worth responding to
        should_respond = await should_bot_respond(content)
        if not should_respond:
            return

    # Strip the @mention
    user_text = message.content.replace(f"<@{bot.user.id}>", "").strip()
    username  = message.author.display_name

    # ── Edit command check FIRST — must run before announcement to avoid confusion ──
    if has_admin_role(message.author):
        edit_cmd = parse_edit_command(user_text)
        if edit_cmd:
            mode        = edit_cmd["mode"]
            instruction = edit_cmd["instruction"]
            edit_ch_id  = edit_cmd["channel_id"] or message.channel.id

            # Use fetch_channel to guarantee we get the channel even if not cached
            try:
                edit_ch = await bot.fetch_channel(edit_ch_id)
            except Exception:
                edit_ch = message.channel

            async def apply_edit(target_msg: discord.Message):
                if target_msg.author.id != bot.user.id:
                    await message.reply("❌ I can only edit my own messages.", mention_author=True)
                    return
                if target_msg.embeds and target_msg.embeds[0].description:
                    original = target_msg.embeds[0].description
                    is_embed = True
                    old_embed = target_msg.embeds[0]
                else:
                    original = target_msg.content or ""
                    is_embed = False
                if not original:
                    await message.reply("❌ That message has no text content I can edit.", mention_author=True)
                    return
                async with message.channel.typing():
                    new_text = await ai_rewrite(original, instruction)
                if is_embed:
                    new_embed = discord.Embed(
                        title=old_embed.title,
                        description=new_text,
                        color=old_embed.color
                    )
                    new_embed.set_footer(text="African Freefire Community  •  africanfreefirecommunity.com  •  (edited)")
                    new_embed.timestamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                    await target_msg.edit(embed=new_embed)
                else:
                    await target_msg.edit(content=new_text)
                await message.reply("✅ Done! Message updated.", mention_author=True)

            try:
                if mode == "id":
                    msg_id = edit_cmd["message_id"]
                    try:
                        target_msg = await edit_ch.fetch_message(msg_id)
                    except discord.NotFound:
                        await message.reply("❌ Couldn't find that message. Check the ID is correct.", mention_author=True)
                        return
                    await apply_edit(target_msg)
                elif mode == "announce":
                    msg_id = last_bot_announcements.get(edit_ch_id)
                    if not msg_id:
                        await message.reply(
                            f"❌ No announcement record for {edit_ch.mention}. Use the message ID instead.",
                            mention_author=True
                        )
                        return
                    target_msg = await edit_ch.fetch_message(msg_id)
                    await apply_edit(target_msg)
                elif mode == "last":
                    # If a target channel was specified, look for last message there
                    # Otherwise fall back to current channel
                    lookup_channel_id = edit_ch_id if edit_ch_id != message.channel.id else message.channel.id
                    msg_id = (
                        last_bot_announcements.get(lookup_channel_id)
                        or last_bot_messages.get(lookup_channel_id)
                        or last_bot_messages.get(message.channel.id)
                    )
                    if not msg_id:
                        await message.reply(
                            f"❌ No record of my last message in {edit_ch.mention}. "
                            "Use the message ID directly — right-click the message → Copy Message ID.",
                            mention_author=True
                        )
                        return
                    target_msg = await edit_ch.fetch_message(msg_id)
                    await apply_edit(target_msg)
            except discord.Forbidden:
                await message.reply("❌ I don't have permission to edit that message.", mention_author=True)
            except Exception as e:
                await message.reply(f"⚠️ Couldn't edit the message. Error: {e}", mention_author=True)
            return

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
            try:
                target_channel = await bot.fetch_channel(target_channel_id)
            except Exception:
                await message.reply("❌ I couldn't find that channel. Make sure I have access to it.", mention_author=True)
                return

        generate_keywords = [
            "formulate", "generate", "write", "create", "draft", "help me",
            "make", "compose", "craft", "prepare", "put together"
        ]
        should_generate = any(kw in user_text.lower() for kw in generate_keywords)

        # Collect attached files
        import io
        image_files = []
        other_files = []
        if message.attachments:
            for attachment in message.attachments:
                file_bytes = await download_attachment(attachment)
                att_type = get_attachment_type(attachment.filename)
                if att_type == "image":
                    image_files.append((attachment.filename, file_bytes))
                else:
                    other_files.append((attachment.filename, file_bytes))

        layout_keywords = ["above", "below", "middle", "between", "then", "followed by",
                           "first image", "second image", "image then text", "text then image",
                           "top", "bottom", "after the text", "before the text"]
        is_multi_layout = len(image_files) > 1 or any(kw in user_text.lower() for kw in layout_keywords)

        # ── Generate the announcement ────────────────────────────────────────
        current_hints = msg_content  # kept for re-generation on feedback

        async def generate_embed_and_content(hints, uid):
            if should_generate or hints:
                try:
                    ann_data = await generate_announcement(hints, uid)
                    emb, ping = build_embed(ann_data)
                    return emb, ping
                except Exception as e:
                    return None, None
            else:
                plain = f"<@{uid}> {hints}" if uid else hints
                emb = discord.Embed(description=plain, color=EMBED_COLORS["announcement"])
                emb.set_footer(text="African Freefire Community  •  africanfreefirecommunity.com")
                emb.timestamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                return emb, None

        async with message.channel.typing():
            embed, ping_content = await generate_embed_and_content(current_hints, target_user_id)

        if embed is None:
            await message.reply("⚠️ Couldn't generate the announcement. Please try again.", mention_author=True)
            return

        # ── PREVIEW LOOP — show preview, wait for approval ───────────────────
        max_attempts = 5
        attempt = 0

        while attempt < max_attempts:
            attempt += 1

            # Build preview embed with header
            preview_embed = discord.Embed(
                title=embed.title,
                description=embed.description,
                color=embed.color
            )
            preview_embed.set_footer(text=f"📋 PREVIEW — will be sent to #{target_channel.name}  •  africanfreefirecommunity.com")
            if embed.timestamp:
                preview_embed.timestamp = embed.timestamp

            # Show preview with images if any
            preview_files = []
            if image_files:
                preview_files = [discord.File(fp=io.BytesIO(fb), filename=fn) for fn, fb in image_files[:1]]

            await message.channel.send(
                content=f"{message.author.mention} **Preview** → will send to <#{target_channel_id}>",
                embed=preview_embed,
                files=preview_files if preview_files else discord.utils.MISSING
            )

            # Show approval prompt
            approval_msg = await message.channel.send(
                "✅ Type `send` to send  |  ✏️ Type your correction to fix it  |  ❌ Type `cancel` to cancel"
            )

            def approval_check(m):
                return (
                    m.author.id == message.author.id
                    and m.channel.id == message.channel.id
                )

            try:
                response = await bot.wait_for("message", check=approval_check, timeout=120.0)
                resp_text = response.content.strip().lower()

                # Clean up the approval prompt and response after reading
                try:
                    await approval_msg.delete()
                    await response.delete()
                except Exception:
                    pass

                if resp_text == "cancel":
                    await message.channel.send("❌ Announcement cancelled.", delete_after=5)
                    return

                elif resp_text == "send":
                    # ── Send to target channel ───────────────────────────────
                    break  # exit loop and send below

                else:
                    # User gave feedback — regenerate with correction
                    async with message.channel.typing():
                        # Combine original hints with the correction
                        new_hints = f"{current_hints}\n\nCorrection: {response.content.strip()}"
                        embed, ping_content = await generate_embed_and_content(new_hints, target_user_id)
                    if embed is None:
                        await message.channel.send("⚠️ Couldn't regenerate. Try again.", delete_after=5)
                        return
                    continue  # show updated preview

            except asyncio.TimeoutError:
                await message.channel.send(
                    "⏱️ No response for 2 minutes. Announcement cancelled.",
                    delete_after=10
                )
                return

        # ── Actually send to target channel ──────────────────────────────────
        try:
            allowed = discord.AllowedMentions(everyone=True, roles=True, users=True)
            sent = None

            if is_multi_layout and image_files:
                text_lower = user_text.lower()
                if re.search(r"\bimage\s+(above|first|on\s+top|before\s+text)\b"
                             r"|\babove\s+the\s+text\b|\bimage\s+then\s+text\b"
                             r"|\btop\b.*\bimage\b", text_lower):
                    order = "images_first"
                elif re.search(r"\bimage\s+(below|after|at\s+the\s+bottom|after\s+text)\b"
                               r"|\bbelow\s+the\s+text\b|\btext\s+then\s+image\b"
                               r"|\bbottom\b.*\bimage\b", text_lower):
                    order = "text_first"
                elif re.search(r"\bmiddle\b|\bbetween\b|\bsandwich\b", text_lower):
                    order = "sandwich"
                else:
                    order = "images_first"

                if order == "images_first":
                    for fname, fbytes in image_files:
                        await target_channel.send(
                            file=discord.File(fp=io.BytesIO(fbytes), filename=fname),
                            allowed_mentions=allowed
                        )
                        await asyncio.sleep(0.5)
                    sent = await target_channel.send(content=ping_content, embed=embed, allowed_mentions=allowed)
                    for fname, fbytes in other_files:
                        await target_channel.send(file=discord.File(fp=io.BytesIO(fbytes), filename=fname))

                elif order == "text_first":
                    sent = await target_channel.send(content=ping_content, embed=embed, allowed_mentions=allowed)
                    for fname, fbytes in image_files:
                        await target_channel.send(
                            file=discord.File(fp=io.BytesIO(fbytes), filename=fname),
                            allowed_mentions=allowed
                        )
                        await asyncio.sleep(0.5)

                elif order == "sandwich":
                    first_fname, first_fbytes = image_files[0]
                    await target_channel.send(
                        file=discord.File(fp=io.BytesIO(first_fbytes), filename=first_fname),
                        allowed_mentions=allowed
                    )
                    await asyncio.sleep(0.5)
                    sent = await target_channel.send(content=ping_content, embed=embed, allowed_mentions=allowed)
                    for fname, fbytes in image_files[1:]:
                        await asyncio.sleep(0.5)
                        await target_channel.send(
                            file=discord.File(fp=io.BytesIO(fbytes), filename=fname),
                            allowed_mentions=allowed
                        )

            elif image_files:
                files_to_send = [discord.File(fp=io.BytesIO(fb), filename=fn) for fn, fb in image_files]
                for fname, fbytes in other_files:
                    files_to_send.append(discord.File(fp=io.BytesIO(fbytes), filename=fname))
                sent = await target_channel.send(
                    content=ping_content, embed=embed,
                    files=files_to_send, allowed_mentions=allowed
                )
            else:
                other_fs = [discord.File(fp=io.BytesIO(fb), filename=fn) for fn, fb in other_files]
                sent = await target_channel.send(
                    content=ping_content, embed=embed,
                    files=other_fs if other_fs else discord.utils.MISSING,
                    allowed_mentions=allowed
                )

            if sent:
                last_bot_announcements[target_channel.id] = sent.id

            await message.channel.send(
                f"✅ Announcement sent to <#{target_channel_id}>!",
                delete_after=10
            )

        except discord.Forbidden:
            await message.reply(
                f"❌ I don't have permission to send messages in <#{target_channel_id}>.",
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

        # ── Mass role operations ──────────────────────────────────────────────
        mass_role_cmd = parse_mass_role_command(user_text)
        if mass_role_cmd:
            action           = mass_role_cmd["action"]
            target_role_id   = mass_role_cmd["target_role_id"]
            condition_role_id = mass_role_cmd["condition_role_id"]
            guild            = message.guild
            target_role      = guild.get_role(target_role_id)

            if not target_role:
                await message.reply("❌ Couldn't find that role.", mention_author=True)
                return

            condition_role = None
            if condition_role_id:
                condition_role = guild.get_role(condition_role_id)
                if not condition_role:
                    await message.reply("❌ Couldn't find the condition role.", mention_author=True)
                    return

            # Build confirmation message
            if action == "remove_all":
                summary = f"Remove **@{target_role.name}** from **everyone** who has it"
            elif action == "remove_if":
                summary = f"Remove **@{target_role.name}** from everyone who has **@{condition_role.name}**"
            elif action == "give_all":
                summary = f"Give **@{target_role.name}** to **every member** in the server"
            elif action == "give_if":
                summary = f"Give **@{target_role.name}** to everyone who has **@{condition_role.name}**"
            else:
                summary = "Unknown action"

            embed = discord.Embed(
                title="⚠️ Confirm Mass Role Action",
                description=f"{summary}\n\n**This will affect multiple members.**\n\nReply `yes` to confirm or `no` to cancel.",
                color=EMBED_COLORS["urgent"]
            )
            embed.set_footer(text=f"Requested by {message.author.display_name} • Expires in 30 seconds")
            await message.reply(embed=embed, mention_author=True)

            def mass_check(m):
                return (
                    m.author.id == message.author.id
                    and m.channel.id == message.channel.id
                    and m.content.lower().strip() in ("yes", "no", "y", "n")
                )

            try:
                confirm = await bot.wait_for("message", check=mass_check, timeout=30.0)
                if confirm.content.lower().strip() not in ("yes", "y"):
                    await message.channel.send("❌ Mass role action cancelled.")
                    return
            except asyncio.TimeoutError:
                await message.channel.send("⏱️ Confirmation timed out. Action cancelled.")
                return

            # Execute — fetch all members and apply
            await message.channel.send(f"⚙️ Working on it... this may take a moment for large servers.")
            affected = 0
            failed   = 0

            try:
                await guild.chunk()  # ensure member cache is full
            except Exception:
                pass

            for member in guild.members:
                if member.bot:
                    continue

                # Determine if this member should be affected
                if action in ("remove_all", "give_all"):
                    should_act = True
                elif action == "remove_if":
                    should_act = condition_role in member.roles
                elif action == "give_if":
                    should_act = condition_role in member.roles
                else:
                    should_act = False

                if not should_act:
                    continue

                # Skip if already has/doesn't have the role
                if action in ("remove_all", "remove_if") and target_role not in member.roles:
                    continue
                if action in ("give_all", "give_if") and target_role in member.roles:
                    continue

                try:
                    success = False
                    retries = 0
                    while not success and retries < 5:
                        try:
                            if action in ("remove_all", "remove_if"):
                                await member.remove_roles(target_role, reason=f"AFC Bot mass action — by {message.author}")
                            else:
                                await member.add_roles(target_role, reason=f"AFC Bot mass action — by {message.author}")
                            affected += 1
                            success = True
                            await asyncio.sleep(0.8)  # safe delay between each member
                        except discord.HTTPException as e:
                            if e.status == 429:  # rate limited
                                retry_after = float(e.response.headers.get("Retry-After", 2))
                                await asyncio.sleep(retry_after + 0.5)
                                retries += 1
                            else:
                                failed += 1
                                success = True  # skip this member
                except Exception:
                    failed += 1

            verb = "removed from" if action in ("remove_all", "remove_if") else "given to"
            result_embed = discord.Embed(
                description=(
                    f"✅ **@{target_role.name}** {verb} **{affected}** member(s)."
                    + (f"\n⚠️ Failed for {failed} member(s)." if failed else "")
                ),
                color=EMBED_COLORS["general"]
            )
            result_embed.set_footer(text=f"Action by {message.author.display_name}")
            await message.channel.send(embed=result_embed)
            return

        # ── Give / Remove role (single user) ─────────────────────────────────
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

        # ── Role management (create, delete, rename, recolor, edit props) ────
        role_manage_cmd = parse_role_manage_command(user_text)
        if role_manage_cmd:
            action   = role_manage_cmd["action"]
            role_id  = role_manage_cmd["role_id"]
            guild    = message.guild

            try:
                if action == "create":
                    name  = role_manage_cmd["name"] or "New Role"
                    color = discord.Color(role_manage_cmd["color"]) if role_manage_cmd["color"] else discord.Color.default()
                    mentionable = role_manage_cmd["mentionable"] or False
                    hoisted     = role_manage_cmd["hoisted"] or False
                    new_role = await guild.create_role(
                        name=name, color=color,
                        mentionable=mentionable, hoist=hoisted,
                        reason=f"AFC Bot — created by {message.author}"
                    )
                    embed = discord.Embed(
                        description=f"✅ Role **{new_role.name}** created — {new_role.mention}",
                        color=new_role.color
                    )
                    embed.set_footer(text=f"Created by {message.author.display_name}")
                    await message.reply(embed=embed, mention_author=True)

                elif action == "delete":
                    role = guild.get_role(role_id)
                    if not role:
                        await message.reply("❌ Couldn't find that role.", mention_author=True)
                        return
                    role_name = role.name
                    await role.delete(reason=f"AFC Bot — deleted by {message.author}")
                    embed = discord.Embed(
                        description=f"🗑️ Role **{role_name}** has been deleted.",
                        color=EMBED_COLORS["urgent"]
                    )
                    embed.set_footer(text=f"Action by {message.author.display_name}")
                    await message.reply(embed=embed, mention_author=True)

                elif action == "rename":
                    role = guild.get_role(role_id)
                    if not role:
                        await message.reply("❌ Couldn't find that role.", mention_author=True)
                        return
                    old_name = role.name
                    await role.edit(name=role_manage_cmd["name"], reason=f"AFC Bot — renamed by {message.author}")
                    embed = discord.Embed(
                        description=f"✅ Role **{old_name}** renamed to **{role.name}**.",
                        color=role.color
                    )
                    embed.set_footer(text=f"Action by {message.author.display_name}")
                    await message.reply(embed=embed, mention_author=True)

                elif action == "recolor":
                    role = guild.get_role(role_id)
                    if not role:
                        await message.reply("❌ Couldn't find that role.", mention_author=True)
                        return
                    new_color = discord.Color(role_manage_cmd["color"]) if role_manage_cmd["color"] else discord.Color.default()
                    await role.edit(color=new_color, reason=f"AFC Bot — recolored by {message.author}")
                    embed = discord.Embed(
                        description=f"✅ Role **{role.name}** color updated.",
                        color=new_color
                    )
                    embed.set_footer(text=f"Action by {message.author.display_name}")
                    await message.reply(embed=embed, mention_author=True)

                elif action == "edit_props":
                    role = guild.get_role(role_id)
                    if not role:
                        await message.reply("❌ Couldn't find that role.", mention_author=True)
                        return
                    kwargs = {}
                    if role_manage_cmd["mentionable"] is not None:
                        kwargs["mentionable"] = role_manage_cmd["mentionable"]
                    if role_manage_cmd["hoisted"] is not None:
                        kwargs["hoist"] = role_manage_cmd["hoisted"]
                    await role.edit(**kwargs, reason=f"AFC Bot — edited by {message.author}")
                    changes = []
                    if "mentionable" in kwargs:
                        changes.append(f"mentionable: **{'yes' if kwargs['mentionable'] else 'no'}**")
                    if "hoist" in kwargs:
                        changes.append(f"hoisted: **{'yes' if kwargs['hoist'] else 'no'}**")
                    embed = discord.Embed(
                        description=f"✅ Role **{role.name}** updated — {', '.join(changes)}.",
                        color=role.color
                    )
                    embed.set_footer(text=f"Action by {message.author.display_name}")
                    await message.reply(embed=embed, mention_author=True)

            except discord.Forbidden:
                await message.reply("❌ I don't have permission to manage that role. Make sure my role is above it in the role list.", mention_author=True)
            except Exception as e:
                await message.reply(f"⚠️ Something went wrong with the role action. Error: {e}", mention_author=True)
            return
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

        # ── Purge messages (MUST come before delete channel check) ───────────
        purge_cmd = parse_purge_command(user_text)
        if purge_cmd:
            mode       = purge_cmd["mode"]
            target_cid = purge_cmd["channel_id"] or message.channel.id
            amount     = purge_cmd["amount"]
            keyword    = purge_cmd["keyword"]
            pu_user_id = purge_cmd["user_id"]
            guild      = message.guild
            try:
                target_ch = await bot.fetch_channel(target_cid)
            except Exception:
                target_ch = message.channel

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
            confirm_bot_msg = await message.reply(embed=embed, mention_author=True)

            # IDs of all confirmation-related messages to clean up after
            cleanup_ids = {
                message.id,           # admin's original purge command
                confirm_bot_msg.id,   # bot's confirmation request
            }

            def purge_check(m):
                return (
                    m.author.id == message.author.id
                    and m.channel.id == message.channel.id
                    and m.content.lower().strip() in ("yes", "no", "y", "n")
                )

            try:
                confirm = await bot.wait_for("message", check=purge_check, timeout=30.0)
                cleanup_ids.add(confirm.id)  # admin's yes/no reply

                if confirm.content.lower().strip() not in ("yes", "y"):
                    cancelled_msg = await message.channel.send("❌ Purge cancelled.")
                    cleanup_ids.add(cancelled_msg.id)
                    # Clean up all confirmation messages
                    await asyncio.sleep(2)
                    for mid in cleanup_ids:
                        try:
                            m = await message.channel.fetch_message(mid)
                            await m.delete()
                        except Exception:
                            pass
                    return
            except asyncio.TimeoutError:
                timeout_msg = await message.channel.send("⏱️ Confirmation timed out. Purge cancelled.")
                cleanup_ids.add(timeout_msg.id)
                await asyncio.sleep(2)
                for mid in cleanup_ids:
                    try:
                        m = await message.channel.fetch_message(mid)
                        await m.delete()
                    except Exception:
                        pass
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
                        # Exclude confirmation messages from the count by filtering
                        def not_cleanup(m): return m.id not in cleanup_ids
                        deleted = await target_ch.purge(limit=amount, check=not_cleanup)
                        deleted_count = len(deleted)

                    elif mode == "keyword":
                        def kw_check(m): return keyword.lower() in m.content.lower() and m.id not in cleanup_ids
                        deleted = await target_ch.purge(limit=None, check=kw_check)
                        deleted_count = len(deleted)
                        async for old_msg in target_ch.history(limit=None):
                            if old_msg.id in cleanup_ids:
                                continue
                            if keyword.lower() in old_msg.content.lower():
                                if await safe_delete(old_msg):
                                    deleted_count += 1
                                    await asyncio.sleep(1.2)

                    elif mode == "user":
                        def user_check(m): return m.author.id == pu_user_id and m.id not in cleanup_ids
                        deleted = await target_ch.purge(limit=None, check=user_check)
                        deleted_count = len(deleted)
                        async for old_msg in target_ch.history(limit=None):
                            if old_msg.id in cleanup_ids:
                                continue
                            if old_msg.author.id == pu_user_id:
                                if await safe_delete(old_msg):
                                    deleted_count += 1
                                    await asyncio.sleep(1.2)

                    elif mode == "all":
                        def not_cleanup_check(m): return m.id not in cleanup_ids
                        deleted = await target_ch.purge(limit=None, check=not_cleanup_check)
                        deleted_count = len(deleted)
                        async for old_msg in target_ch.history(limit=None):
                            if old_msg.id in cleanup_ids:
                                continue
                            if await safe_delete(old_msg):
                                deleted_count += 1
                                await asyncio.sleep(1.2)

                    # Send result, then clean up all confirmation messages + result after 4 seconds
                    result_embed = discord.Embed(
                        description=f"✅ **{deleted_count}** message(s) deleted from {target_ch.mention}.",
                        color=EMBED_COLORS["general"]
                    )
                    result_embed.set_footer(text=f"Action by {message.author.display_name} • This log will self-delete in 4s")
                    result_msg = await message.channel.send(embed=result_embed)

                    # Wait then silently delete all confirmation/log messages
                    await asyncio.sleep(4)
                    for mid in list(cleanup_ids) + [result_msg.id]:
                        try:
                            m = await message.channel.fetch_message(mid)
                            await m.delete()
                        except Exception:
                            pass

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

    sent_reply = await message.reply(reply, mention_author=True)
    last_bot_messages[message.channel.id] = sent_reply.id
    if needs_support:
        await send_support_redirect(message)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
