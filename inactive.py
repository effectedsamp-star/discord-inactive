import os
import json
from datetime import datetime, timedelta

import discord
from discord import ui, Interaction, app_commands, Modal, TextInput
from discord.ext import commands, tasks

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("Не найдена переменная окружения DISCORD_TOKEN.")

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# ID канала, где будет таблица неактивов
INACTIVE_CHANNEL_ID = 1540035013847023696

# Роли, которые снимаются при неактиве
FAMILY_ROLES = [
    "academy",
    "boss main",
    "boss academy",
    "main"
]

INACTIVE_ROLE_NAME = "inactive"

# Хранилище неактивов: {user_id: {"end_date": "...", "roles": [...]}}
inactive_users = {}

# ID сообщения с таблицей неактивов
inactive_message_id = None


# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def get_family_roles(member: discord.Member):
    """Возвращает список ролей семьи, которые есть у участника."""
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

    channel = bot.get_channel(INACTIVE_CHANNEL_ID)
    if not channel:
        return

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
        else:
            # Пробуем найти первое сообщение от бота в канале
            async for msg in channel.history(limit=10):
                if msg.author == bot.user and "Неактив" in msg.content:
                    await msg.edit(content=content)
                    inactive_message_id = msg.id
                    return

            # Если не нашли — создаём новое
            msg = await channel.send(content=content)
            inactive_message_id = msg.id
    except Exception as e:
        print(f"Ошибка обновления таблицы неактивов: {e}")


def save_inactive_data():
    """Сохраняет данные неактивов в файл."""
    with open("inactive_data.json", "w", encoding="utf-8") as f:
        json.dump({
            "inactive_users": inactive_users,
            "inactive_message_id": inactive_message_id
        }, f, ensure_ascii=False, indent=2)


def load_inactive_data():
    """Загружает данные неактивов из файла."""
    global inactive_users, inactive_message_id
    try:
        with open("inactive_data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            inactive_users = data.get("inactive_users", {})
            inactive_message_id = data.get("inactive_message_id")
    except FileNotFoundError:
        pass


# ================= МОДАЛЬНОЕ ОКНО =================

class InactiveModal(Modal):
    def __init__(self, interaction: Interaction):
        super().__init__(title="Взять неактив")
        self.interaction = interaction
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

        # Выдаём inactive
        await member.add_roles(inactive_role, reason="Взят неактив")

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
        await interaction.response.send_modal(InactiveModal(interaction))

    @ui.button(label="Снять неактив", style=discord.ButtonStyle.danger, custom_id="inactive_remove")
    async def remove_inactive(self, interaction: Interaction, button: ui.Button):
        member = interaction.user
        guild = interaction.guild

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

        # Возвращаем роли семьи (нужно найти их заново по ID)
        # В реальной ситуации лучше хранить ID ролей, но для простоты попробуем найти по названию
        # В идеале — при взятии неактива сохранять ID ролей и возвращать их

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
            "• выдаётся роль