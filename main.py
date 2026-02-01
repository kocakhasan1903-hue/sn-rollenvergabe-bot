import os
import json
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

CONFIG_FILE = "config.json"
FAMILIES_FILE = "families.json"

if not TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN fehlt in Railway Variables")

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
        return {}
    with open(FAMILIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_families(data):
    with open(FAMILIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

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
                    f"**Ablauf:**\n"
                    f"1) Button drücken\n"
                    f"2) Familie auswählen\n"
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

        if not data:
            await interaction.response.send_message("❌ Familie existiert nicht (Staff muss sie anlegen).", ephemeral=True)
            return

        if self.password.value.strip() != str(data.get("password", "")):
            await log(interaction.guild, f"🚫 Passwort falsch: {interaction.user} → {self.family_name}")
            await interaction.response.send_message("❌ Passwort falsch.", ephemeral=True)
            return

        role_id = str(data.get("role_id", "")).strip()
        if not role_id.isdigit():
            await interaction.response.send_message("❌ Rolle-ID ungültig (Staff muss Familie neu setzen).", ephemeral=True)
            return

        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message("❌ Rolle existiert nicht (mehr). Staff muss Familie neu setzen.", ephemeral=True)
            return

        member = interaction.user

        # Nickname setzen (optional)
        try:
            await member.edit(nick=f"{self.ic_first.value.strip()} {self.ic_last.value.strip()}"[:32])
        except:
            pass

        # Einreise entfernen
        einreise = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE_NAME)
        if einreise:
            try:
                await member.remove_roles(einreise)
            except:
                pass

        # Familienrolle geben
        try:
            await member.add_roles(role)
        except:
            await interaction.response.send_message(
                "❌ Rolle konnte nicht vergeben werden. Prüfe Rollen-Hierarchie & 'Rollen verwalten'.",
                ephemeral=True
            )
            return

        await log(interaction.guild, f"✅ Rollenvergabe: {interaction.user} → {role.name} ({self.family_name})")
        await interaction.response.send_message(
            f"✅ Erfolgreich!\n🏴 Familie: **{self.family_name}**\n🏷️ Rolle: **{role.name}**",
            ephemeral=True
        )

class FamilySelect(discord.ui.Select):
    def __init__(self):
        fams = load_families()
        options = []
        for name in sorted(fams.keys())[:25]:
            options.append(discord.SelectOption(label=name, value=name, emoji="🏴"))

        super().__init__(
            placeholder="🏴 Wähle deine Familie",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        fam = self.values[0]
        await interaction.response.send_modal(VerifyModal(fam))

class FamilyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(FamilySelect())

class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Rollenvergabe starten", style=discord.ButtonStyle.danger, emoji="🧬")
    async def start(self, interaction: discord.Interaction, _):
        if not load_families():
            await interaction.response.send_message("⚠️ Noch keine Familien angelegt.", ephemeral=True)
            return
        await interaction.response.send_message("👇 Familie auswählen:", ephemeral=True, view=FamilyView())

# ---------- Auto UI posting (edit instead of spam) ----------
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
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    name = name.strip()

    fams[name] = {"password": passwort.strip(), "role_id": str(rolle.id)}
    save_families(fams)

    await log(interaction.guild, f"🛠️ familie_add: {interaction.user} → {name} = {rolle.name}")
    await interaction.response.send_message(f"✅ Familie **{name}** gespeichert → {rolle.mention}", ephemeral=True)

@bot.tree.command(name="familie_remove", description="Familie entfernen (Staff)")
async def familie_remove(interaction: discord.Interaction, name: str):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    name = name.strip()

    if name not in fams:
        await interaction.response.send_message("❌ Familie nicht gefunden.", ephemeral=True)
        return

    del fams[name]
    save_families(fams)

    await log(interaction.guild, f"🗑️ familie_remove: {interaction.user} → {name}")
    await interaction.response.send_message(f"✅ Familie **{name}** wurde entfernt.", ephemeral=True)

@bot.tree.command(name="familie_edit", description="Familie bearbeiten (Passwort/Rolle) (Staff)")
@app_commands.describe(name="Familienname", passwort="Neues Passwort (optional)", rolle="Neue Rolle (optional)")
async def familie_edit(interaction: discord.Interaction, name: str, passwort: str = None, rolle: discord.Role = None):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    name = name.strip()

    if name not in fams:
        await interaction.response.send_message("❌ Familie nicht gefunden.", ephemeral=True)
        return

    changed = []
    if passwort is not None and passwort.strip():
        fams[name]["password"] = passwort.strip()
        changed.append("Passwort")

    if rolle is not None:
        fams[name]["role_id"] = str(rolle.id)
        changed.append(f"Rolle → {rolle.name}")

    if not changed:
        await interaction.response.send_message("⚠️ Nichts geändert. Gib passwort und/oder rolle an.", ephemeral=True)
        return

    save_families(fams)
    await log(interaction.guild, f"✏️ familie_edit: {interaction.user} → {name} | {', '.join(changed)}")
    await interaction.response.send_message(f"✅ Familie **{name}** aktualisiert: {', '.join(changed)}", ephemeral=True)

@bot.tree.command(name="familien_liste", description="Familien anzeigen (Staff)")
async def familien_liste(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    if not fams:
        await interaction.response.send_message("ℹ️ Keine Familien vorhanden.", ephemeral=True)
        return

    txt = "\n".join([f"🏴 **{k}**" for k in sorted(fams.keys())])
    await interaction.response.send_message(txt, ephemeral=True)

@bot.tree.command(name="ui_update", description="UI im Verify-Channel neu posten/aktualisieren (Staff)")
async def ui_update(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if not ch:
        await interaction.response.send_message("❌ Verify-Channel ID falsch oder Bot sieht den Channel nicht.", ephemeral=True)
        return

    msg = await ensure_ui_message(ch)
    await interaction.response.send_message(f"✅ UI aktualisiert: {msg.jump_url}", ephemeral=True)

# ---------- Events ----------
@bot.event
async def setup_hook():
    # GLOBAL sync -> Commands überall verfügbar (kann beim ersten Mal dauern)
    await bot.tree.sync()
    print("🌍 Slash Commands GLOBAL synced")
    print("🌳 Commands:", [c.name for c in bot.tree.get_commands()])

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")

    # Auto UI update in the configured verify channel (on this server)
    for g in bot.guilds:
        ch = g.get_channel(VERIFY_CHANNEL_ID)
        if ch:
            try:
                await ensure_ui_message(ch)
                await log(g, "📌 Rollenvergabe UI wurde automatisch aktualisiert.")
            except:
                pass

@bot.event
async def on_member_join(member: discord.Member):
    # Give auto role "Einreise"
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        try:
            await member.add_roles(role)
        except:
            pass

bot.run(TOKEN)
