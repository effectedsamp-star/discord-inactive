import os
import json
import asyncio
from datetime import datetime, timedelta

import discord
from discord import ui, Interaction, app_commands
from discord.ext import commands, tasks


# ============================================================
# НАСТРОЙКИ
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "Не найдена переменная окружения DISCORD_TOKEN."
    )

# ID канала, где будет таблица неактивов
INACTIVE_CHANNEL_ID = 1540035013847023696

# Файл для хранения данных
DATA_FILE = "inactive_data.json"

# Роли, которые снимаются при оформлении неактива
FAMILY_ROLES = [
    "academy main",
    "boss",
    "academy boss",
    "main"
]

# Название роли неактива
INACTIVE_ROLE_NAME = "inactive"


# ============================================================
# INTENTS
# ============================================================

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True


# ============================================================
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# ============================================================

# Формат:
#
# {
#     "123456789": {
#         "guild_id": 123456789,
#         "end_date": "2026-09-30T15:30:00",
#         "roles": [111111111, 222222222]
#     }
# }
#
inactive_users = {}

# ID сообщения с таблицей
inactive_message_id = None

# Чтобы данные не загружались повторно после переподключения
data_loaded = False


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def is_family_role(role: discord.Role) -> bool:
    """Проверяет, является ли роль семейной."""
    family_role_names = {
        role_name.lower()
        for role_name in FAMILY_ROLES
    }

    return role.name.lower() in family_role_names


def get_family_roles(member: discord.Member):
    """Возвращает семейные роли участника."""
    return [
        role
        for role in member.roles
        if is_family_role(role)
    ]


def get_inactive_role(guild: discord.Guild):
    """Находит роль inactive на сервере."""
    for role in guild.roles:
        if role.name.lower() == INACTIVE_ROLE_NAME.lower():
            return role

    return None


def parse_date(data: dict):
    """Безопасно получает дату окончания."""
    try:
        return datetime.fromisoformat(data["end_date"])
    except (KeyError, TypeError, ValueError):
        return None


def get_days_left(end_date: datetime) -> int:
    """Возвращает количество оставшихся дней."""
    difference = end_date - datetime.now()
    return max(0, difference.days + 1)


def save_inactive_data():
    """Сохраняет данные неактивов в JSON-файл."""
    data = {
        "inactive_users": inactive_users,
        "inactive_message_id": inactive_message_id
    }

    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4
            )

        print("💾 Данные неактивов сохранены")

    except OSError as error:
        print(
            f"❌ Ошибка сохранения данных: {error}"
        )


def load_inactive_data():
    """Загружает данные неактивов из JSON-файла."""
    global inactive_users
    global inactive_message_id

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        inactive_users = data.get(
            "inactive_users",
            {}
        )

        inactive_message_id = data.get(
            "inactive_message_id"
        )

        print(
            f"💾 Загружено неактивов: "
            f"{len(inactive_users)}"
        )

    except FileNotFoundError:
        print(
            "💾 Файл inactive_data.json не найден. "
            "Будет создан новый."
        )

    except json.JSONDecodeError as error:
        print(
            f"❌ Ошибка чтения JSON-файла: {error}"
        )

    except OSError as error:
        print(
            f"❌ Ошибка загрузки данных: {error}"
        )


# ============================================================
# СОЗДАНИЕ EMBED-ТАБЛИЦЫ
# ============================================================

def create_inactive_embed() -> discord.Embed:
    """Создаёт Embed с текущими неактивами."""
    embed = discord.Embed(
        title="🛡️ Renamed Mafia | Inactive",
        description=(
            "Если вы временно не можете принимать участие "
            "в жизни семьи, оформите неактив через кнопки ниже.\n\n"
            "**При оформлении неактива:**\n"
            "🔸 семейные роли временно снимаются;\n"
            "🔸 выдаётся роль `inactive`;\n"
            "🔸 участник не учитывается в активности;\n"
            "🔸 после окончания срока роли возвращаются автоматически."
        ),
        color=discord.Color.from_rgb(
            190,
            145,
            55
        ),
        timestamp=datetime.now()
    )

    inactive_lines = []

    for user_id, data in inactive_users.items():
        end_date = parse_date(data)

        if end_date is None:
            continue

        guild_id = data.get("guild_id")
        guild = None

        if guild_id:
            guild = bot.get_guild(int(guild_id))

        member = None

        if guild:
            member = guild.get_member(
                int(user_id)
            )

        if member:
            user_text = member.mention
        else:
            user_text = f"<@{user_id}>"

        days_left = get_days_left(end_date)

        inactive_lines.append(
            f"• {user_text}\n"
            f"  └ До **{end_date.strftime('%d.%m.%Y %H:%M')}** "
            f"· осталось **{days_left} дн.**"
        )

    if inactive_lines:
        embed.add_field(
            name="📋 Текущие неактивы",
            value="\n".join(inactive_lines),
            inline=False
        )
    else:
        embed.add_field(
            name="📋 Текущие неактивы",
            value="```Нет участников в неактиве.```",
            inline=False
        )

    embed.set_footer(
        text="Renamed • Таблица обновляется автоматически"
    )

    return embed


# ============================================================
# ОБНОВЛЕНИЕ ТАБЛИЦЫ
# ============================================================

async def update_inactive_table():
    """Создаёт или редактирует таблицу неактивов."""
    global inactive_message_id

    print(
        f"🔄 Обновление таблицы в канале "
        f"{INACTIVE_CHANNEL_ID}"
    )

    channel = bot.get_channel(
        INACTIVE_CHANNEL_ID
    )

    if channel is None:
        for guild in bot.guilds:
            possible_channel = guild.get_channel(
                INACTIVE_CHANNEL_ID
            )

            if possible_channel:
                channel = possible_channel
                break

    if channel is None:
        print(
            "❌ Канал таблицы не найден. "
            "Проверь INACTIVE_CHANNEL_ID."
        )
        return

    if not isinstance(channel, discord.TextChannel):
        print(
            "❌ Указанный канал не является текстовым."
        )
        return

    embed = create_inactive_embed()

    try:
        # Пытаемся изменить сохранённое сообщение
        if inactive_message_id:
            try:
                message = await channel.fetch_message(
                    inactive_message_id
                )

                await message.edit(
                    embed=embed,
                    view=InactivePanelView()
                )

                print("✅ Таблица обновлена")
                return

            except discord.NotFound:
                print(
                    "⚠️ Старое сообщение не найдено. "
                    "Создаём новое."
                )

        # Ищем старую панель среди последних сообщений
        async for message in channel.history(limit=50):
            if (
                message.author == bot.user
                and message.embeds
                and message.embeds[0].title
                and "Renamed Mafia | Inactive"
                in message.embeds[0].title
            ):
                inactive_message_id = message.id

                await message.edit(
                    embed=embed,
                    view=InactivePanelView()
                )

                save_inactive_data()

                print(
                    "✅ Найдено старое сообщение "
                    "и обновлено"
                )
                return

        # Если сообщение не найдено — создаём новое
        message = await channel.send(
            embed=embed,
            view=InactivePanelView()
        )

        inactive_message_id = message.id

        save_inactive_data()

        print("✅ Создана новая таблица")

    except discord.Forbidden:
        print(
            "❌ У бота нет прав на отправку сообщений "
            "или чтение истории канала."
        )

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка Discord при обновлении таблицы: "
            f"{error}"
        )


# ============================================================
# ВОССТАНОВЛЕНИЕ РОЛЕЙ
# ============================================================

async def restore_user_roles(
    member: discord.Member,
    data: dict,
    reason: str
):
    """Снимает inactive и возвращает старые роли."""
    saved_role_ids = data.get(
        "roles",
        []
    )

    roles_to_add = []

    for role_id in saved_role_ids:
        role = member.guild.get_role(
            int(role_id)
        )

        if role and role not in member.roles:
            roles_to_add.append(role)

    inactive_role = get_inactive_role(
        member.guild
    )

    try:
        if inactive_role and inactive_role in member.roles:
            await member.remove_roles(
                inactive_role,
                reason=reason
            )

        if roles_to_add:
            await member.add_roles(
                *roles_to_add,
                reason=reason
            )

        print(
            f"✅ Роли восстановлены для "
            f"{member}"
        )

    except discord.Forbidden:
        print(
            f"❌ Бот не может изменить роли "
            f"{member}. Проверь Manage Roles "
            f"и иерархию ролей."
        )

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка восстановления ролей: "
            f"{error}"
        )


# ============================================================
# ПОДТВЕРЖДЕНИЕ ОФОРМЛЕНИЯ
# ============================================================

class ConfirmInactiveView(ui.View):
    def __init__(
        self,
        member: discord.Member,
        days: int
    ):
        super().__init__(timeout=120)

        self.member = member
        self.days = days

    @ui.button(
        label="Подтвердить",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="inactive_confirm_button"
    )
    async def confirm(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        member = self.member
        guild = interaction.guild

        if guild is None:
            await interaction.response.edit_message(
                content="❌ Сервер не найден.",
                embed=None,
                view=None
            )
            return

        user_id = str(member.id)

        if user_id in inactive_users:
            await interaction.response.edit_message(
                content=(
                    "❌ Вы уже находитесь "
                    "в неактиве."
                ),
                embed=None,
                view=None
            )
            return

        inactive_role = get_inactive_role(
            guild
        )

        if inactive_role is None:
            await interaction.response.edit_message(
                content=(
                    f"❌ Не найдена роль "
                    f"`{INACTIVE_ROLE_NAME}`."
                ),
                embed=None,
                view=None
            )
            return

        if guild.me is None:
            await interaction.response.edit_message(
                content=(
                    "❌ Не удалось определить "
                    "бота на сервере."
                ),
                embed=None,
                view=None
            )
            return

        if inactive_role >= guild.me.top_role:
            await interaction.response.edit_message(
                content=(
                    "❌ Роль `inactive` находится "
                    "выше роли бота.\n\n"
                    "Подними роль бота выше роли "
                    "`inactive`."
                ),
                embed=None,
                view=None
            )
            return

        roles_to_remove = get_family_roles(
            member
        )

        # Сохраняем роли ДО удаления
        saved_role_ids = [
            role.id for role in roles_to_remove
        ]

        try:
            if roles_to_remove:
                await member.remove_roles(
                    *roles_to_remove,
                    reason="Взят неактив"
                )

            if inactive_role not in member.roles:
                await member.add_roles(
                    inactive_role,
                    reason="Взят неактив"
                )

        except discord.Forbidden:
            await interaction.response.edit_message(
                content=(
                    "❌ У бота недостаточно прав "
                    "для управления ролями.\n\n"
                    "Проверь право Manage Roles "
                    "и положение роли бота."
                ),
                embed=None,
                view=None
            )
            return

        except discord.HTTPException as error:
            await interaction.response.edit_message(
                content=f"❌ Ошибка Discord: {error}",
                embed=None,
                view=None
            )
            return

        end_date = datetime.now() + timedelta(
            days=self.days
        )

        inactive_users[user_id] = {
            "guild_id": guild.id,
            "end_date": end_date.isoformat(),
            "roles": saved_role_ids
        }

        save_inactive_data()

        # Обновление сразу после оформления
        await update_inactive_table()

        result_embed = discord.Embed(
            title="✅ Неактив оформлен",
            description=(
                f"{member.mention}, неактив "
                f"успешно оформлен."
            ),
            color=discord.Color.green()
        )

        result_embed.add_field(
            name="⏳ Срок",
            value=f"{self.days} дн.",
            inline=True
        )

        result_embed.add_field(
            name="📅 Окончание",
            value=end_date.strftime(
                "%d.%m.%Y в %H:%M"
            ),
            inline=True
        )

        result_embed.set_footer(
            text=(
                "Роли будут возвращены "
                "автоматически"
            )
        )

        await interaction.response.edit_message(
            content=None,
            embed=result_embed,
            view=None
        )

    @ui.button(
        label="Отмена",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="inactive_cancel_button"
    )
    async def cancel(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        await interaction.response.edit_message(
            content="❌ Оформление отменено.",
            embed=None,
            view=None
        )


# ============================================================
# ВЫБОР СРОКА ОТ 1 ДО 14 ДНЕЙ
# ============================================================

class DaysSelect(ui.Select):
    def __init__(self, member: discord.Member):
        self.member = member

        options = []

        for days in range(1, 15):
            options.append(
                discord.SelectOption(
                    label=f"{days} дней",
                    value=str(days),
                    description=(
                        f"Неактив на {days} дней"
                    ),
                    emoji="🕒"
                )
            )

        super().__init__(
            placeholder=(
                "Выберите срок от 1 до 14 дней"
            ),
            min_values=1,
            max_values=1,
            options=options,
            custom_id="inactive_days_select"
        )

    async def callback(
        self,
        interaction: Interaction
    ):
        days = int(self.values[0])

        end_date = datetime.now() + timedelta(
            days=days
        )

        embed = discord.Embed(
            title="⚠️ Подтверждение неактива",
            description=(
                f"Вы выбрали неактив "
                f"на **{days} дней**.\n\n"
                f"Дата окончания:\n"
                f"**{end_date.strftime('%d.%m.%Y в %H:%M')}**\n\n"
                "После подтверждения семейные роли "
                "будут временно сняты."
            ),
            color=discord.Color.orange()
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=ConfirmInactiveView(
                self.member,
                days
            )
        )


# ============================================================
# КНОПКА ЗАКРЫТИЯ МЕНЮ
# ============================================================

class CancelSelectionButton(ui.Button):
    def __init__(self):
        super().__init__(
            label="Закрыть",
            emoji="✖️",
            style=discord.ButtonStyle.secondary,
            custom_id="inactive_close_button"
        )

    async def callback(
        self,
        interaction: Interaction
    ):
        await interaction.response.edit_message(
            content="Меню закрыто.",
            embed=None,
            view=None
        )


# ============================================================
# VIEW ВЫБОРА СРОКА
# ============================================================

class DaysSelectView(ui.View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=180)

        self.add_item(
            DaysSelect(member)
        )

        self.add_item(
            CancelSelectionButton()
        )


# ============================================================
# ПОДТВЕРЖДЕНИЕ СНЯТИЯ НЕАКТИВА
# ============================================================

class RemoveInactiveConfirmView(ui.View):
    def __init__(
        self,
        member: discord.Member,
        data: dict
    ):
        super().__init__(timeout=120)

        self.member = member
        self.data = data

    @ui.button(
        label="Снять неактив",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="inactive_remove_confirm_button"
    )
    async def confirm_remove(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        user_id = str(self.member.id)

        if user_id not in inactive_users:
            await interaction.response.edit_message(
                content="❌ Неактив уже снят.",
                embed=None,
                view=None
            )
            return

        await restore_user_roles(
            self.member,
            self.data,
            "Досрочное снятие неактива"
        )

        inactive_users.pop(
            user_id,
            None
        )

        save_inactive_data()

        # Обновление сразу после снятия
        await update_inactive_table()

        embed = discord.Embed(
            title="✅ Неактив снят",
            description=(
                f"{self.member.mention}, "
                "неактив снят досрочно.\n\n"
                "Сохранённые роли возвращены."
            ),
            color=discord.Color.green()
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=None
        )

    @ui.button(
        label="Отмена",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="inactive_remove_cancel_button"
    )
    async def cancel_remove(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        await interaction.response.edit_message(
            content="❌ Действие отменено.",
            embed=None,
            view=None
        )


# ============================================================
# ГЛАВНАЯ ПОСТОЯННАЯ ПАНЕЛЬ
# ============================================================

class InactivePanelView(ui.View):
    """
    Постоянная панель.

    Кнопка ручного обновления отсутствует.
    Таблица обновляется автоматически через задачу.
    """

    def __init__(self):
        # timeout=None нужен для работы после перезапуска
        super().__init__(timeout=None)

    @ui.button(
        label="Взять неактив",
        emoji="🟡",
        style=discord.ButtonStyle.primary,
        custom_id="inactive_take_button",
        row=0
    )
    async def take_inactive(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Не удалось определить участника.",
                ephemeral=True
            )
            return

        if str(member.id) in inactive_users:
            await interaction.response.send_message(
                "❌ Вы уже находитесь в неактиве.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🕒 Оформление неактива",
            description=(
                "Выберите срок в меню ниже.\n\n"
                "Доступный срок: "
                "**от 1 до 14 дней**."
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="Меню доступно только вам"
        )

        await interaction.response.send_message(
            embed=embed,
            view=DaysSelectView(member),
            ephemeral=True
        )

    @ui.button(
        label="Снять неактив",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        custom_id="inactive_remove_button",
        row=0
    )
    async def remove_inactive(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        member = interaction.user
        user_id = str(member.id)

        if user_id not in inactive_users:
            await interaction.response.send_message(
                "❌ Вы не находитесь в неактиве.",
                ephemeral=True
            )
            return

        data = inactive_users[user_id]

        embed = discord.Embed(
            title="⚠️ Досрочное снятие неактива",
            description=(
                "Вы действительно хотите снять "
                "неактив досрочно?\n\n"
                "Сохранённые семейные роли "
                "будут возвращены."
            ),
            color=discord.Color.orange()
        )

        await interaction.response.send_message(
            embed=embed,
            view=RemoveInactiveConfirmView(
                member,
                data
            ),
            ephemeral=True
        )


# ============================================================
# КЛАСС БОТА
# ============================================================

class InactiveBot(commands.Bot):
    async def setup_hook(self):
        # Регистрируем постоянную view после перезапуска
        self.add_view(
            InactivePanelView()
        )

        try:
            synced = await self.tree.sync()

            print(
                f"📋 Синхронизировано команд: "
                f"{len(synced)}"
            )

        except discord.HTTPException as error:
            print(
                f"❌ Ошибка синхронизации команд: "
                f"{error}"
            )


bot = InactiveBot(
    command_prefix="!",
    intents=INTENTS
)


# ============================================================
# КОМАНДА СОЗДАНИЯ ПАНЕЛИ
# ============================================================

@bot.tree.command(
    name="панель",
    description="Создать панель неактива"
)
@app_commands.describe(
    channel="Канал для размещения панели"
)
@app_commands.guild_only()
async def inactive_panel(
    interaction: Interaction,
    channel: discord.TextChannel
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Команда доступна только администраторам.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🛡️ Renamed Mafia | Система inactive",
        description=(
            "Временно не можете участвовать "
            "в жизни семьи?\n"
            "Оформите неактив через меню ниже.\n\n"
            "**Что произойдёт:**\n"
            "🟡 семейные роли будут сняты;\n"
            "🟡 будет выдана роль `inactive`;\n"
            "🟡 участник не будет учитываться "
            "в активности;\n"
            "🟡 роли автоматически вернутся "
            "после окончания срока."
        ),
        color=discord.Color.from_rgb(
            190,
            145,
            55
        )
    )

    embed.add_field(
        name="⏳ Доступный срок",
        value="От **1 до 14 дней**",
        inline=True
    )

    embed.add_field(
        name="🔄 Возврат ролей",
        value="Автоматический",
        inline=True
    )

    embed.add_field(
        name="📋 Обновление таблицы",
        value="Каждую минуту",
        inline=True
    )

    embed.add_field(
        name="📌 Важно",
        value=(
            "Указывайте реальный срок неактива. "
            "После оформления срок можно снять досрочно."
        ),
        inline=False
    )

    embed.set_footer(
        text="Renamed Mafia • Система управления неактивами"
    )

    try:
        await channel.send(
            embed=embed,
            view=InactivePanelView()
        )

        await interaction.response.send_message(
            f"✅ Панель создана в {channel.mention}.",
            ephemeral=True
        )

        print(
            f"✅ Панель создана в канале "
            f"{channel.name}"
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ У бота нет прав на отправку сообщений "
            "в выбранный канал.",
            ephemeral=True
        )

    except discord.HTTPException as error:
        await interaction.response.send_message(
            f"❌ Ошибка Discord: {error}",
            ephemeral=True
        )


# ============================================================
# ПРОВЕРКА ОКОНЧАНИЯ НЕАКТИВОВ
# ============================================================

@tasks.loop(minutes=1)
async def check_inactive_expiry():
    """
    Проверяет окончание неактивов каждую минуту.
    При окончании срока роли возвращаются.
    """
    print("🔄 Проверка сроков неактивов...")

    now = datetime.now()
    users_to_remove = []

    for user_id, data in list(
        inactive_users.items()
    ):
        end_date = parse_date(data)

        if end_date is None:
            print(
                f"⚠️ Некорректная дата у "
                f"пользователя {user_id}"
            )

            users_to_remove.append(user_id)
            continue

        if now >= end_date:
            users_to_remove.append(user_id)

    for user_id in users_to_remove:
        data = inactive_users.get(user_id)

        if not data:
            continue

        guild_id = data.get("guild_id")
        guild = None

        if guild_id:
            guild = bot.get_guild(
                int(guild_id)
            )

        member = None

        if guild:
            member = guild.get_member(
                int(user_id)
            )

        if member:
            await restore_user_roles(
                member,
                data,
                "Истёк срок неактива"
            )

            print(
                f"⏰ Неактив закончился у "
                f"{member}"
            )
        else:
            print(
                f"⚠️ Участник {user_id} "
                "не найден на сервере."
            )

        inactive_users.pop(
            user_id,
            None
        )

    if users_to_remove:
        save_inactive_data()
        await update_inactive_table()


@check_inactive_expiry.before_loop
async def before_check_inactive_expiry():
    await bot.wait_until_ready()


# ============================================================
# АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ ТАБЛИЦЫ
# ============================================================

@tasks.loop(minutes=1)
async def auto_update_table():
    """
    Автоматически обновляет таблицу каждую минуту.
    Кнопки для ручного обновления нет.
    """
    await update_inactive_table()


@auto_update_table.before_loop
async def before_auto_update_table():
    await bot.wait_until_ready()


# ============================================================
# СОБЫТИЕ ГОТОВНОСТИ
# ============================================================

@bot.event
async def on_ready():
    global data_loaded

    print("=" * 60)
    print(f"✅ Бот подключён: {bot.user}")
    print(f"🆔 ID бота: {bot.user.id}")
    print(f"🌐 Серверов: {len(bot.guilds)}")

    for guild in bot.guilds:
        print(
            f"• {guild.name} "
            f"(ID: {guild.id})"
        )

    if not data_loaded:
        load_inactive_data()
        data_loaded = True

    if not check_inactive_expiry.is_running():
        check_inactive_expiry.start()

    if not auto_update_table.is_running():
        auto_update_table.start()

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Нужен неактив? Так возьми его!"
        )
    )

    await asyncio.sleep(2)

    # Первое обновление сразу после запуска
    await update_inactive_table()

    print("=" * 60)


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("🚀 Запуск бота...")
    print(f"🔑 Токен найден: {bool(TOKEN)}")

    try:
        bot.run(TOKEN)

    except discord.LoginFailure:
        print(
            "❌ Неверный токен Discord-бота."
        )

    except discord.PrivilegedIntentsRequired:
        print(
            "❌ Не включены Privileged Gateway Intents.\n"
            "Включи Server Members Intent и "
            "Message Content Intent."
        )

    except Exception as error:
        print(
            f"❌ Критическая ошибка запуска: "
            f"{error}"
        )
