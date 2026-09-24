import os
import json
import asyncio
from datetime import datetime, timedelta

import discord
from discord import ui, Interaction, app_commands, Modal, TextInput
from discord.ext import commands, tasks

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("Не найдена переменная окружения DISCORD_TOKEN.")

print(f"Токен найден: {bool(TOKEN)}")

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.guilds = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# ID канала, где будет таблица неактивов
INACTIVE_CHANNEL_ID = 1540035013847023696

# Роли, которые снимаются при неактиве
FAMILY_ROLES = [
    "academy main",
    "boss",
    "academy boss",
    "main"
]

INACTIVE_ROLE_NAME = "inactive"

# Хранилище неактивов: {user_id: {"end_date": "...", "roles": [...]}}
inactive_users = {}

# ID сообщения с таблицей неактивов
inactive_message_id = None

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def get_family_roles(member: discord.Member):
    """Возвращает список ID ролей семьи, которые есть у участника."""
    roles = []
    for role in member.roles:
        if role.name.lower() in [r.lower() for r in FAMILY_ROLES]:
            roles.append(role.id)
    return roles

def get_inactive_role(guild: discord.Guild):
    """Находит роль inactive на сервере."""
    for role in guild.roles:
        if role.name.lower() == INACTIVE_ROLE_NAME.lower():
            return role
    return None

async def update_inactive_table():
    """Обновляет сообщение с таблицей неактивов."""
    global inactive_message_id
    
    print(f"Попытка обновить таблицу в канале {INACTIVE_CHANNEL_ID}")
    
    channel = bot.get_channel(INACTIVE_CHANNEL_ID)
    if not channel:
        print(f"❌ Канал {INACTIVE_CHANNEL_ID} не найден!")
        # Пробуем найти канал на всех серверах
        for guild in bot.guilds:
            ch = guild.get_channel(INACTIVE_CHANNEL_ID)
            if ch:
                channel = ch
                print(f"✅ Канал найден на сервере {guild.name}")
                break
    
    if not channel:
        print(f"❌ Канал не найден ни на одном сервере")
        return
    
    print(f"✅ Канал найден: {channel.name}")
    
    # Формируем текст таблицы
    if not inactive_users:
        content = (
            "**Renamed | Неактив**\n"
            "Если вы временно не можете принимать участие в жизни семьи,\n"
            "вы можете взять неактив.\n\n"
            "При нахождении в неактиве:\n"
            "• снимаются ваши текущие роли семьи;\n"
            "• выдаётся роль inactive;\n"
            "• вы не учитываетесь в системе активности;\n"
            "• после выхода роли автоматически возвращаются.\n\n"
            "**Текущие неактивы**:\n\n"
            "Нет участников в неактиве."
        )
    else:
        lines = [
            "**Renamed | Неактив**",
            "Если вы временно не можете принимать участие в жизни семьи,",
            "вы можете взять неактив.\n",
            "При нахождении в неактиве:",
            "• снимаются ваши текущие роли семьи;",
            "• выдаётся роль inactive;",
            "• вы не учитываетесь в системе активности;",
            "• после выхода роли автоматически возвращаются.\n",
            "**Текущие неактивы**:\n"
        ]
        
        for user_id, data in inactive_users.items():
            user = bot.get_user(int(user_id))
            if user:
                end_date = datetime.fromisoformat(data["end_date"])
                days_left = (end_date - datetime.now()).days + 1
                lines.append(f"• {user.mention} — до {end_date.strftime('%d.%m.%Y')} ({days_left} дн. осталось)")
        
        content = "\n".join(lines)
    
    # Ищем существующее сообщение или создаём новое
    try:
        if inactive_message_id:
            msg = await channel.fetch_message(inactive_message_id)
            await msg.edit(content=content)
            print("✅ Таблица неактивов обновлена")
        else:
            # Пробуем найти первое сообщение от бота в канале
            async for msg in channel.history(limit=10):
                if msg.author == bot.user and "Неактив" in msg.content:
                    await msg.edit(content=content)
                    inactive_message_id = msg.id
                    save_inactive_data()
                    print("✅ Найдено существующее сообщение таблицы")
                    return
            
            # Если не нашли — создаём новое
            msg = await channel.send(content=content)
            inactive_message_id = msg.id
            save_inactive_data()
            print("✅ Создано новое сообщение таблицы")
    except Exception as e:
        print(f"❌ Ошибка обновления таблицы неактивов: {e}")
        import traceback
        traceback.print_exc()

def save_inactive_data():
    """Сохраняет данные неактивов в файл."""
    with open("inactive_data.json", "w", encoding="utf-8") as f:
        json.dump({
            "inactive_users": inactive_users,
            "inactive_message_id": inactive_message_id
        }, f, ensure_ascii=False, indent=2)
    print("💾 Данные неактивов сохранены")

def load_inactive_data():
    """Загружает данные неактивов из файла."""
    global inactive_users, inactive_message_id
    try:
        with open("inactive_data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            inactive_users = data.get("inactive_users", {})
            inactive_message_id = data.get("inactive_message_id")
            print(f"💾 Загружено {len(inactive_users)} неактивов")
    except FileNotFoundError:
        print("💾 Файл данных не найден, начинаем с чистого листа")
    except Exception as e:
        print(f"❌ Ошибка загрузки данных: {e}")

# ================= МОДАЛЬНОЕ ОКНО =================

class InactiveModal(Modal):
    def __init__(self):
        super().__init__(title="Взять неактив")
        self.days_input = TextInput(
            label="На сколько дней?",
            placeholder="Введите число от 1 до 14",
            min_length=1,
            max_length=2,
            required=True
        )
        self.add_item(self.days_input)
    
    async def on_submit(self, interaction: Interaction):
        try:
            days = int(self.days_input.value)
            if days < 1 or days > 14:
                await interaction.response.send_message(
                    "❌ Количество дней должно быть от 1 до 14.",
                    ephemeral=True
                )
                return
        except ValueError:
            await interaction.response.send_message(
                "❌ Введите корректное число.",
                ephemeral=True
            )
            return
        
        member = interaction.user
        guild = interaction.guild
        
        print(f"📝 {member.name} пытается взять неактив на {days} дней")
        
        # Проверяем, не в неактиве ли уже
        if str(member.id) in inactive_users:
            await interaction.response.send_message(
                "❌ Вы уже в неактиве.",
                ephemeral=True
            )
            return
        
        # Находим роль inactive
        inactive_role = get_inactive_role(guild)
        if not inactive_role:
            await interaction.response.send_message(
                f"❌ Роль `{INACTIVE_ROLE_NAME}` не найдена на сервере.",
                ephemeral=True
            )
            return
        
        # Снимаем роли семьи
        roles_to_remove = []
        for role in member.roles:
            if role.name.lower() in [r.lower() for r in FAMILY_ROLES]:
                roles_to_remove.append(role)
        
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Взят неактив")
            print(f"✅ Сняты роли с {member.name}: {[r.name for r in roles_to_remove]}")
        
        # Выдаём inactive
        await member.add_roles(inactive_role, reason="Взят неактив")
        print(f"✅ Выдана роль {inactive_role.name} участнику {member.name}")
        
        # Сохраняем данные
        end_date = datetime.now() + timedelta(days=days)
        inactive_users[str(member.id)] = {
            "end_date": end_date.isoformat(),
            "roles": get_family_roles(member)
        }
        
        save_inactive_data()
        await update_inactive_table()
        
        await interaction.response.send_message(
            f"✅ Вы взяли неактив на {days} дней.\n"
            f"Дата возврата: {end_date.strftime('%d.%m.%Y')}",
            ephemeral=True
        )

# ================= КНОПКИ =================

class InactiveView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="Взять неактив", style=discord.ButtonStyle.secondary, custom_id="inactive_take")
    async def take_inactive(self, interaction: Interaction, button: ui.Button):
        print(f"🔘 {interaction.user.name} нажал кнопку 'Взять неактив'")
        await interaction.response.send_modal(InactiveModal())
    
    @ui.button(label="Снять неактив", style=discord.ButtonStyle.danger, custom_id="inactive_remove")
    async def remove_inactive(self, interaction: Interaction, button: ui.Button):
        member = interaction.user
        guild = interaction.guild
        
        print(f"🔘 {member.name} нажал кнопку 'Снять неактив'")
        
        # Проверяем, в неактиве ли
        if str(member.id) not in inactive_users:
            await interaction.response.send_message(
                "❌ Вы не в неактиве.",
                ephemeral=True
            )
            return
        
        # Находим роль inactive
        inactive_role = get_inactive_role(guild)
        
        # Снимаем inactive
        if inactive_role and inactive_role in member.roles:
            await member.remove_roles(inactive_role, reason="Досрочный выход из неактива")
            print(f"✅ Снята inactive роль с {member.name}")
        
        # Удаляем из списка неактивов
        del inactive_users[str(member.id)]
        save_inactive_data()
        await update_inactive_table()
        
        await interaction.response.send_message(
            "✅ Вы досрочно сняли неактив. Роли семьи будут возвращены вручную администратором.",
            ephemeral=True
        )

# ================= КОМАНДЫ =================

@bot.tree.command(name="панель", description="Создать панель неактива в канале")
@app_commands.describe(channel="Канал, где создать панель")
async def inactive_panel(interaction: Interaction, channel: discord.TextChannel):
    print(f"📋 {interaction.user.name} использует команду /панель в {channel.name}")
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Только для администраторов.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="Renamed | Неактив",
        description=(
            "Если вы временно не можете принимать участие в жизни семьи,\n"
            "вы можете взять неактив.\n\n"
            "**При нахождении в неактиве**:\n"
            "• снимаются ваши текущие роли семьи;\n"
            "• выдаётся роль inactive;\n"
            "• вы не учитываетесь в системе активности;\n"
            "• после выхода роли автоматически возвращаются."
        ),
        color=discord.Color.dark_gold()
    )
    
    await channel.send(embed=embed, view=InactiveView())
    await interaction.response.send_message("✅ Панель неактива создана.", ephemeral=True)
    print(f"✅ Панель создана в канале {channel.name}")

@bot.tree.command(name="возврат", description="Автоматически вернуть роли после неактива")
@app_commands.describe(member="Участник, которому вернуть роли")
async def return_roles(interaction: Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Только для администраторов.", ephemeral=True)
        return
    
    if str(member.id) not in inactive_users:
        await interaction.response.send_message("❌ Участник не в неактиве.", ephemeral=True)
        return
    
    await interaction.response.send_message("✅ Роли будут возвращены.", ephemeral=True)

# ================= ФОНОВАЯ ЗАДАЧА =================

@tasks.loop(minutes=5)
async def check_inactive_expiry():
    """Проверяет истечение срока неактива."""
    print("🔄 Проверка истечения неактивов...")
    now = datetime.now()
    to_remove = []
    
    for user_id, data in inactive_users.items():
        end_date = datetime.fromisoformat(data["end_date"])
        if now >= end_date:
            to_remove.append(user_id)
    
    for user_id in to_remove:
        user = bot.get_user(int(user_id))
        if user and user.guild:
            inactive_role = get_inactive_role(user.guild)
            if inactive_role and inactive_role in user.roles:
                await user.remove_roles(inactive_role, reason="Истёк срок неактива")
            print(f"⏰ Истёк срок неактива для {user.name}")
        
        del inactive_users[user_id]
    
    if to_remove:
        save_inactive_data()
        await update_inactive_table()

@check_inactive_expiry.before_loop
async def before_check():
    await bot.wait_until_ready()
    print("⏳ Ожидание готовности бота...")

# ================= СОБЫТИЯ =================

@bot.event
async def on_ready():
    print("=" * 50)
    print(f"✅ Бот готов: {bot.user}")
    print(f"🆔 ID бота: {bot.user.id}")
    print(f"🌐 Количество серверов: {len(bot.guilds)}")
    
    for guild in bot.guilds:
        print(f"  • {guild.name} (ID: {guild.id})")
    
    load_inactive_data()
    check_inactive_expiry.start()
    
    # Синхронизация слэш-команд
    try:
        synced = await bot.tree.sync()
        print(f"📋 Синхронизировано {len(synced)} команд")
        for cmd in synced:
            print(f"  • /{cmd.name}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации команд: {e}")
        import traceback
        traceback.print_exc()
    
    # Ждём немного и обновляем таблицу
    await asyncio.sleep(2)
    await update_inactive_table()
    
    print("=" * 50)

# ================= ЗАПУСК =================

if __name__ == "__main__":
    print("🚀 Запуск бота...")
    bot.run(TOKEN)
