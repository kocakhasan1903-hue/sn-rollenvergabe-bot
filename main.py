import os
import json
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt")

CONFIG_FILE = "config.json"

# ✅ Persistent path (Railway Volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
FAMILIES_FILE = os.path.join(DATA_DIR, "families.json")

# ---------- Load config ----------
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

VERIFY_CHANNEL_ID = int(CONFIG["verify_channel_id"])
LOG_CHANNEL_ID = int(CONFIG["log_channel_id"])
AUTO_ROLE_NAME = CONFIG["auto_role_name"]
EMBED_TITLE = CONFIG["embed_title"]
EMBED_TEXT = CONFIG["embed_text"]
STAFF_ROLE_IDS = set(int(x) for x in CONFIG["staff_role_ids"])

# ---------- Files ----------
def load_families():
    if not os.path.exists(FAMILIES_FILE):
        # create empty file once
        with open(FAMILIES_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}
    with open(FAMILIES_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_families(data):
    tmp = FAMILIES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, FAMILIES_FILE)

# ---------- Bot ----------
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

def is_staff(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.id in STAFF_ROLE_IDS for r in member.roles)

async def log(guild: discord.Guild, msg: str):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(msg)
        except:
            pass

# ---------- UI ----------
def build_embed():
    embed = discord.Embed(
        title=f"🔥 {EMBED_TITLE}",
        description=f"🧬 {EMBED_TEXT}\n\n"
                    f"1) Button klicken\n"
                    f"2) Familie wählen\n"
                    f"3) IC Daten + Passwort\n"
                    f"4) Rolle erhalten ✅",
        color=discord.Color.red()
    )
    embed.set_footer(text="Sin Nombre • Rollenvergabe System")
    return embed

class VerifyModal(discord.ui.Modal, title="🧬 Rollenvergabe"):
    ic_first = discord.ui.TextInput(label="IC Vorname", max_length=32)
    ic_last = discord.ui.TextInput(label="IC Nachname", max_length=32)
    password = discord.ui.TextInput(label="Familienpasswort", max_length=64)

    def __init__(self, family_name: str):
        super().__init__()
        self.family_name = family_name

    async def on_submit(self, interaction: discord.Interaction):
        families = load_families()
        data = families.get(self.family_name)

        if not data or self.password.value.strip() != str(data.get("password", "")):
            await interaction.response.send_message("❌ Passwort falsch.", ephemeral=True)
            return

        role = interaction.guild.get_role(int(data["role_id"]))
        if not role:
            await interaction.response.send_message("❌ Rolle existiert nicht (mehr).", ephemeral=True)
            return

        member = interaction.user
        nickname = f"{self.ic_first.value.strip()} {self.ic_last.value.strip()} | {self.family_name}"[:32]
        try:
            await member.edit(nick=nickname)
        except:
            pass

        einreise = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE_NAME)
        if einreise:
            try:
                await member.remove_roles(einreise)
            except:
                pass

        # alte Familienrollen entfernen
        for fam in families.values():
            old_role = interaction.guild.get_role(int(fam["role_id"]))
            if old_role and old_role in member.roles:
                try:
                    await member.remove_roles(old_role)
                except:
                    pass

        try:
            await member.add_roles(role)
        except:
            await interaction.response.send_message(
                "❌ Rolle konnte nicht vergeben werden. Rollen-Hierarchie prüfen.",
                ephemeral=True
            )
            return

        await log(interaction.guild, f"✅ Rollenvergabe: {member} → {role.name} ({self.family_name})")
        await interaction.response.send_message("✅ Verifizierung erfolgreich!", ephemeral=True)

class FamilySelect(discord.ui.Select):
    def __init__(self):
        fams = load_families()
        options = [discord.SelectOption(label=name, value=name, emoji="🏴") for name in sorted(fams.keys())[:25]]
        super().__init__(placeholder="🏴 Familie auswählen", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VerifyModal(self.values[0]))

class FamilyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ✅ dauerhaft
        self.add_item(FamilySelect())

class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ✅ dauerhaft

    @discord.ui.button(label="Rollenvergabe starten", style=discord.ButtonStyle.danger, emoji="🧬")
    async def start(self, interaction: discord.Interaction, _):
        if not load_families():
            await interaction.response.send_message("⚠️ Noch keine Familien angelegt.", ephemeral=True)
            return
        await interaction.response.send_message("👇 Familie auswählen:", ephemeral=True, view=FamilyView())

async def ensure_ui_message(channel: discord.TextChannel) -> discord.Message:
    async for msg in channel.history(limit=30):
        if msg.author.id == bot.user.id and msg.embeds:
            if msg.embeds[0].title and EMBED_TITLE.lower() in msg.embeds[0].title.lower():
                await msg.edit(embed=build_embed(), view=StartView())
                return msg
    return await channel.send(embed=build_embed(), view=StartView())

# ---------- Staff Commands ----------
@bot.tree.command(name="familie_add", description="Familie anlegen (Staff)")
async def familie_add(interaction: discord.Interaction, name: str, passwort: str, rolle: discord.Role):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

    fams = load_families()
    fams[name.strip()] = {"password": passwort.strip(), "role_id": str(rolle.id)}
    save_families(fams)

    # ✅ UI automatisch refreshen (damit neue Familie sofort sichtbar ist)
    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if ch:
        await ensure_ui_message(ch)

    await interaction.response.send_message(f"✅ Familie **{name}** gespeichert → {rolle.mention}", ephemeral=True)

@bot.tree.command(name="familie_remove", description="Familie löschen (Staff)")
async def familie_remove(interaction: discord.Interaction, name: str):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

    fams = load_families()
    name = name.strip()
    if name not in fams:
        return await interaction.response.send_message("❌ Familie nicht gefunden.", ephemeral=True)

    del fams[name]
    save_families(fams)

    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if ch:
        await ensure_ui_message(ch)

    await interaction.response.send_message(f"🗑️ Familie **{name}** entfernt.", ephemeral=True)

@bot.tree.command(name="ui_update", description="UI neu posten/aktualisieren (Staff)")
async def ui_update(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if not ch:
        return await interaction.response.send_message("❌ Verify-Channel nicht gefunden (ID prüfen).", ephemeral=True)

    msg = await ensure_ui_message(ch)
    await interaction.response.send_message(f"✅ UI aktualisiert: {msg.jump_url}", ephemeral=True)

# ---------- Events ----------
@bot.event
async def setup_hook():
    await bot.tree.sync()
    print("🌍 Slash Commands GLOBAL synced")

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")
    for g in bot.guilds:
        ch = g.get_channel(VERIFY_CHANNEL_ID)
        if ch:
            await ensure_ui_message(ch)
            await log(g, "📌 Rollenvergabe UI wurde automatisch aktualisiert.")

@bot.event
async def on_member_join(member: discord.Member):
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        try:
            await member.add_roles(role)
        except:
            pass

bot.run(TOKEN)
