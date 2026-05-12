import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime, timedelta
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# ---- CONFIGURATION ----
TOKEN = os.getenv("DISCORD_TOKEN")
PLACES_MAX = 7
SALON_DEFAUT = 1503786814803279876
# -----------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

FICHIER = "seances.json"

def charger_seances():
    if os.path.exists(FICHIER):
        with open(FICHIER, "r") as f:
            return json.load(f)
    return {}

def sauvegarder_seances(data):
    with open(FICHIER, "w") as f:
        json.dump(data, f, indent=2)

async def get_affiche(film):
    url = f"https://www.omdbapi.com/?t={film}&apikey=trilogy"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                data = await resp.json()
                if data.get("Poster") and data["Poster"] != "N/A":
                    return data["Poster"]
    except:
        pass
    return None

def creer_embed(s, cle):
    inscrits = s["inscrits"]
    places_restantes = PLACES_MAX - len(inscrits)
    liste_inscrits = "\n".join([f"• {nom}" for nom in inscrits]) if inscrits else "Personne pour l'instant"

    embed = discord.Embed(
        title=f"🎬 {s['film']}",
        description=f"📅 **Date :** {s['date']}\n⏰ **Heure :** {s['heure']}",
        color=discord.Color.dark_red()
    )
    embed.add_field(name=f"👥 Inscrits ({len(inscrits)}/{PLACES_MAX})", value=liste_inscrits, inline=False)

    if places_restantes > 0:
        embed.add_field(name="🎟️ Places restantes", value=f"**{places_restantes}** place(s) disponible(s)", inline=False)
    else:
        embed.add_field(name="🎟️ Places restantes", value="**Complet !** 🔴", inline=False)

    if s.get("affiche"):
        embed.set_image(url=s["affiche"])

    embed.set_footer(text="Clique sur un bouton pour t'inscrire ou te désinscrire")
    return embed

class BoutonSeance(discord.ui.View):
    def __init__(self, cle):
        super().__init__(timeout=None)
        self.cle = cle

    @discord.ui.button(label="S'inscrire", emoji="✅", style=discord.ButtonStyle.success, custom_id="inscrire")
    async def inscrire(self, interaction: discord.Interaction, button: discord.ui.Button):
        seances = charger_seances()
        cle = self.cle
        if cle not in seances:
            await interaction.response.send_message("❌ Séance introuvable.", ephemeral=True)
            return
        nom = interaction.user.display_name
        if nom in seances[cle]["inscrits"]:
            await interaction.response.send_message("⚠️ Tu es déjà inscrit !", ephemeral=True)
            return
        if len(seances[cle]["inscrits"]) >= PLACES_MAX:
            await interaction.response.send_message("🔴 Désolé, la séance est complète !", ephemeral=True)
            return
        seances[cle]["inscrits"].append(nom)
        sauvegarder_seances(seances)
        await interaction.response.send_message(f"✅ Tu es inscrit à **{seances[cle]['film']}** le {seances[cle]['date']} à {seances[cle]['heure']} !", ephemeral=True)
        await interaction.message.edit(embed=creer_embed(seances[cle], cle), view=BoutonSeance(cle))

    @discord.ui.button(label="Se désinscrire", emoji="❌", style=discord.ButtonStyle.danger, custom_id="desinscrire")
    async def desinscrire(self, interaction: discord.Interaction, button: discord.ui.Button):
        seances = charger_seances()
        cle = self.cle
        if cle not in seances:
            await interaction.response.send_message("❌ Séance introuvable.", ephemeral=True)
            return
        nom = interaction.user.display_name
        if nom not in seances[cle]["inscrits"]:
            await interaction.response.send_message("⚠️ Tu n'es pas inscrit à cette séance.", ephemeral=True)
            return
        seances[cle]["inscrits"].remove(nom)
        sauvegarder_seances(seances)
        await interaction.response.send_message(f"👋 Tu t'es désinscrit de **{seances[cle]['film']}** !", ephemeral=True)
        await interaction.message.edit(embed=creer_embed(seances[cle], cle), view=BoutonSeance(cle))

@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commande(s) synchronisée(s)")
    except Exception as e:
        print(e)
    bot.loop.create_task(verifier_rappels())

async def verifier_rappels():
    await bot.wait_until_ready()
    while not bot.is_closed():
        seances = charger_seances()
        maintenant = datetime.now()
        demain = maintenant + timedelta(days=1)
        for cle, s in seances.items():
            try:
                date_seance = datetime.strptime(f"{s['date']} {s['heure']}", "%d/%m/%Y %Hh%M")
                if demain.date() == date_seance.date() and not s.get("rappel_envoye"):
                    channel_id = s.get("channel_id", SALON_DEFAUT)
                    channel = bot.get_channel(channel_id)
                    if channel:
                        inscrits = ", ".join(s["inscrits"]) if s["inscrits"] else "personne"
                        await channel.send(
                            f"🔔 **Rappel !** La séance **{s['film']}** a lieu **demain** à **{s['heure']}** !\n"
                            f"👥 Inscrits : {inscrits}"
                        )
                        seances[cle]["rappel_envoye"] = True
                        sauvegarder_seances(seances)
            except:
                pass
        await asyncio.sleep(3600)

@bot.tree.command(name="ajouter_seance", description="Ajouter une séance de cinéma")
@app_commands.describe(film="Nom du film", date="Date (ex: 25/12/2025)", heure="Heure (ex: 20h30)", salon="Salon où poster la séance (optionnel)")
async def ajouter_seance(interaction: discord.Interaction, film: str, date: str, heure: str, salon: discord.TextChannel = None):
    seances = charger_seances()
    cle = f"{film}_{date}_{heure}"
    if cle in seances:
        await interaction.response.send_message("❌ Cette séance existe déjà !", ephemeral=True)
        return
    await interaction.response.defer()
    affiche = await get_affiche(film)

    # Utilise le salon choisi ou le salon par défaut
    channel = salon if salon else bot.get_channel(SALON_DEFAUT)
    if not channel:
        channel = interaction.channel

    seances[cle] = {
        "film": film,
        "date": date,
        "heure": heure,
        "inscrits": [],
        "affiche": affiche,
        "channel_id": channel.id,
        "rappel_envoye": False
    }
    sauvegarder_seances(seances)
    await channel.send(embed=creer_embed(seances[cle], cle), view=BoutonSeance(cle))
    await interaction.followup.send(f"✅ Séance ajoutée dans {channel.mention} !", ephemeral=True)

@bot.tree.command(name="seances", description="Voir toutes les séances disponibles")
async def voir_seances(interaction: discord.Interaction):
    seances = charger_seances()
    if not seances:
        await interaction.response.send_message("📭 Aucune séance disponible pour le moment.")
        return
    await interaction.response.defer()
    for cle, s in seances.items():
        channel_id = s.get("channel_id", SALON_DEFAUT)
        channel = bot.get_channel(channel_id) or interaction.channel
        await channel.send(embed=creer_embed(s, cle), view=BoutonSeance(cle))
    await interaction.followup.send("📋 Voici toutes les séances !", ephemeral=True)

@bot.tree.command(name="supprimer_seance", description="Supprimer une séance (admin uniquement)")
@app_commands.describe(film="Nom du film", date="Date (ex: 25/12/2025)", heure="Heure (ex: 20h30)")
@app_commands.checks.has_permissions(administrator=True)
async def supprimer_seance(interaction: discord.Interaction, film: str, date: str, heure: str):
    seances = charger_seances()
    cle = f"{film}_{date}_{heure}"
    if cle not in seances:
        await interaction.response.send_message("❌ Séance introuvable.", ephemeral=True)
        return
    del seances[cle]
    sauvegarder_seances(seances)
    await interaction.response.send_message(f"🗑️ Séance **{film}** du {date} à {heure} supprimée.")

bot.run(TOKEN)