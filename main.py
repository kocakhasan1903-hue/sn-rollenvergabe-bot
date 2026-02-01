import os
import json
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ================== ENV ==================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt")

# ================== FILES ==================
CONFIG_FILE = "config.json"
FAMILIES_FILE = "families.json"

# ================== CONFIG ==================
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

VERIFY_CHANNEL_ID = int(CONFIG["verify_channel_id"])
LOG_CHANNEL_ID = int(CONFIG["log_channel_id"])
AUTO_ROLE_NAME = CONFIG["auto_role_name"]
EMBED_TITLE = CONFIG["embed_title"]
EMBED_TEXT = CONFIG["embed_text"]
STAFF_ROLE_IDS = set(int(x) for x in CONFIG["staff_role_ids"])

# ================== BOT ==================
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================== HELPERS ==================
def load_families():
    if not os.path.exists(FAMILIES_FILE):
        return {}
    with open(FAMILIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_families(data):
    with open(FAMILIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_staff(member: discord.Member):
    return member.guild_permissions.administrator or any(
        r.id in STAFF_ROLE_IDS for r in member.roles
    )

async def log(guild: discord.Guild, msg: str):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(msg)
        except:
            pass

# ================== UI ==================
def build_embed():
    return discord.Embed(
        title=f"🔥 {EMBED_TITLE}",
        description=f"🧬 {EMBED_TEXT}\n\n"
                    "1️⃣ Button klicken\n"
                    "2️⃣ Familie wählen\n"
                    "3️⃣ IC-Daten eingeben\n"
                    "4️⃣ Rolle erhalten",
        color=discord.Color.red()
    )

class VerifyModal(discord.ui.Modal, title="🧬 Rollenvergabe"):
    ic_first = discord.ui.TextInput(label="IC Vorname")
    ic_last = discord.ui.TextInput(label="IC Nachname")
    password = discord.ui.TextInput(label="Familienpasswort")

    def __init__(self, family):
        super().__init__()
        self.family = family

    async def on_submit(self, interaction: discord.Interaction):
        families = load_families()
        data = families.get(self.family)

        if not data or self.password.value != data["password"]:
            await interaction.response.send_message("❌ Passwort falsch.", ephemeral=True)
            return

        role = interaction.guild.get_role(int(data["role_id"]))
        if not role:
            await interaction.response.send_message("❌ Rolle existiert nicht.", ephemeral=True)
            return

        member = interaction.user

        # Nickname setzen
        nickname = f"{self.ic_first.value} {self.ic_last.value} | {self.family}"[:32]
        try:
            await member.edit(nick=nickname)
        except:
            pass

        # Einreise entfernen
        einreise = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
        if einreise:
            try:
                await member.remove_roles(einreise)
            except:
                pass

        # Alte Familienrollen entfernen
        for fam in families.values():
            old_role = interaction.guild.get_role(int(fam["role_id"]))
            if old_role and old_role in member.roles:
                try:
                    await member.remove_roles(old_role)
                except:
                    pass

        # Neue Rolle geben
        try:
            await member.add_roles(role)
        except:
            await interaction.response.send_message(
                "❌ Rolle konnte nicht vergeben werden. Rollen-Hierarchie prüfen.",
                ephemeral=True
            )
            return

        await log(member.guild, f"✅ {member} → {role.name}")
        await interaction.response.send_message("✅ Verifizierung erfolgreich!", ephemeral=True)

class FamilySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=name, value=name, emoji="🏴")
            for name in load_families().keys()
        ]
        super().__init__(
            placeholder="🏴 Familie auswählen",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VerifyModal(self.values[0]))

class FamilyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(FamilySelect())

class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Rollenvergabe starten", style=discord.ButtonStyle.danger, emoji="🧬")
    async def start(self, interaction: discord.Interaction, _):
        if not load_families():
            await interaction.response.send_message("⚠️ Keine Familien eingerichtet.", ephemeral=True)
            return
        await interaction.response.send_message("👇 Familie auswählen:", ephemeral=True, view=FamilyView())

async def ensure_ui(channel):
    async for msg in channel.history(limit=20):
        if msg.author == bot.user and msg.embeds:
            await msg.edit(embed=build_embed(), view=StartView())
            return
    await channel.send(embed=build_embed(), view=StartView())

# ================== STAFF COMMANDS ==================
@bot.tree.command(name="familie_add")
async def familie_add(interaction: discord.Interaction, name: str, passwort: str, rolle: discord.Role):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

    fams = load_families()
    fams[name] = {"password": passwort, "role_id": str(rolle.id)}
    save_families(fams)
    await interaction.response.send_message(f"✅ Familie **{name}** hinzugefügt.", ephemeral=True)

@bot.tree.command(name="familie_remove")
async def familie_remove(interaction: discord.Interaction, name: str):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

    fams = load_families()
    if name not in fams:
        return await interaction.response.send_message("❌ Familie nicht gefunden.", ephemeral=True)

    del fams[name]
    save_families(fams)
    await interaction.response.send_message(f"🗑️ Familie **{name}** entfernt.", ephemeral=True)

@bot.tree.command(name="familie_change")
async def familie_change(interaction: discord.Interaction, user: discord.Member, familie: str):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

    fams = load_families()
    if familie not in fams:
        return await interaction.response.send_message("❌ Familie existiert nicht.", ephemeral=True)

    role = interaction.guild.get_role(int(fams[familie]["role_id"]))
    if not role:
        return await interaction.response.send_message("❌ Rolle existiert nicht.", ephemeral=True)

    for fam in fams.values():
        old_role = interaction.guild.get_role(int(fam["role_id"]))
        if old_role and old_role in user.roles:
            await user.remove_roles(old_role)

    await user.add_roles(role)

    base = (user.nick or user.name).split("|")[0].strip()
    try:
        await user.edit(nick=f"{base} | {familie}"[:32])
    except:
        pass

    await interaction.response.send_message(f"🔁 {user.mention} ist jetzt **{familie}**.", ephemeral=True)

@bot.tree.command(name="ui_update")
async def ui_update(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if not ch:
        return await interaction.response.send_message("❌ Verify-Channel nicht gefunden.", ephemeral=True)

    await ensure_ui(ch)
    await interaction.response.send_message("✅ UI aktualisiert.", ephemeral=True)

# ================== EVENTS ==================
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
            await ensure_ui(ch)
            await log(g, "📌 Rollenvergabe UI wurde automatisch aktualisiert.")

@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        try:
            await member.add_roles(role)
        except:
            pass

bot.run(TOKEN)
