from json import dump, load

from highrise import CurrencyItem, Item, User
from services.storage import load_json, save_json


TIP_BARS = {
    10000: ("gold_bar_10k", 1000),
    5000: ("gold_bar_5000", 500),
    1000: ("gold_bar_1k", 100),
    500: ("gold_bar_500", 50),
    100: ("gold_bar_100", 10),
    50: ("gold_bar_50", 5),
    10: ("gold_bar_10", 1),
    5: ("gold_bar_5", 1),
    1: ("gold_bar_1", 1),
}


class TipManager:
    def __init__(self, data_file: str):
        self.data_file = data_file
        self.tip_data = self._load_tip_data()

    async def handle_tip(self, highrise, bot_id: str, sender: User, receiver: User,
                         tip: CurrencyItem | Item) -> None:
        if not isinstance(tip, CurrencyItem):
            return

        print(f"[TIP    ] {sender.username} tipped {tip.amount}g -> {receiver.username}")
        if receiver.id != bot_id:
            return

        user_data = self.tip_data.setdefault(
            sender.id, {"username": sender.username, "total_tips": 0}
        )
        user_data["total_tips"] += tip.amount
        self._write_tip_data(sender, tip.amount)
        await highrise.chat(
            f"<#FFCC66>💛 ¡Muchas gracias @{sender.username} por tu propina de {tip.amount}g! 🪙"
        )

    async def handle_command(self, bot, command: str, user_id: str) -> str | None:
        highrise = bot.highrise
        if command.startswith("!top"):
            formatted_tippers = [
                f"{index}. {user_data['username']} ({user_data['total_tips']}g)"
                for index, (_, user_data) in enumerate(self.get_top_tippers(), start=1)
            ]
            tipper_message = "\n".join(formatted_tippers)
            return f"<#FFCC66>🏆 TOP DE PROPINAS 🏆\n<#FFFFFF>{tipper_message}"

        if command.startswith("!get "):
            username = command.split(" ", 1)[1].replace("@", "")
            tip_amount = self.get_user_tip_amount(username)
            if tip_amount is not None:
                return f"<#66FF99>💰 {username} ha dado {tip_amount}g."
            return f"<#FFCC66>🔎 {username} todavía no ha dado propina."

        if command.startswith("!wallet"):
            wallet = await highrise.get_wallet()
            for currency in wallet.content:
                if currency.type == "gold":
                    return f"<#FFCC66>👛 Mi billetera tiene {currency.amount}g."
            return "<#FFCC66>👛 No hay oro en la billetera."

        parts = command.split()
        if parts and parts[0] in ("!tipme", "!tipall", "!tip"):
            if parts[0] == "!tip" and len(parts) == 3:
                username = parts[1].lstrip("@")
                amount_text = parts[2]
                target_id = await bot.get_user_id(username)
                if not target_id:
                    return "<#FFCC66>🔎 Usuario no encontrado en la sala."
            elif parts[0] == "!tipme" and len(parts) == 2:
                target_id = user_id
                amount_text = parts[1]
            elif parts[0] == "!tipall" and len(parts) == 2:
                target_id = None
                amount_text = parts[1]
            else:
                return "<#FFCC66>💰 Uso: !tipme <cantidad>, !tip @usuario <cantidad> o !tipall <cantidad>"

            try:
                amount = int(amount_text)
            except ValueError:
                return "<#FFCC66>🔢 La cantidad debe ser un número entero."
            if amount <= 0:
                return "<#FFCC66>🔢 La cantidad debe ser mayor que 0."

            recipients = []
            if parts[0] == "!tipall":
                room_users = await highrise.get_room_users()
                recipients = [
                    (room_user.id, room_user.username)
                    for room_user, _ in room_users.content
                    if room_user.id != bot.bot_id
                ]
                if not recipients:
                    return "<#FFCC66>🪙 No hay usuarios a quienes enviar propinas."
            else:
                recipient_username = username if parts[0] == "!tip" else "el usuario solicitante"
                recipients = [(target_id, recipient_username)]

            bars = self._make_tip_bars(amount)
            total_cost = sum(cost for _, cost in bars) * len(recipients)
            wallet_amount = await self._get_gold_amount(highrise)
            if wallet_amount < total_cost:
                return f"<#FF6666>💸 No hay suficiente oro. Necesitas {total_cost}g y tienes {wallet_amount}g."

            successful_recipients = 0
            for recipient_id, recipient_username in recipients:
                for bar, _ in bars:
                    result = await highrise.tip_user(recipient_id, bar)
                    if result != "success":
                        print(
                            f"[TIP ERROR] No se pudo enviar {amount}g a "
                            f"@{recipient_username}: {result}"
                        )
                        return "<#FF6666>⚠️ La propina no pudo enviarse completamente."
                successful_recipients += 1
                if parts[0] == "!tipall":
                    await highrise.chat(
                        f"<#FFCC66>💝 @{recipient_username} recibió {amount}g de propina."
                    )
                if parts[0] == "!tip":
                    print(
                        f"[TIP OUT  ] Enviados {amount}g a "
                        f"@{recipient_username} ({recipient_id})"
                    )

            if parts[0] == "!tipall":
                print(
                    f"[TIP ALL   ] Enviados {amount}g a "
                    f"{successful_recipients} usuarios."
                )
            await highrise.chat(
                f"<#66FF99>💝 Propina enviada: {amount}g a "
                f"{successful_recipients} usuario(s)."
            )
            return None

        return None

    def _make_tip_bars(self, amount: int) -> list[tuple[str, int]]:
        bars = []
        for value, (bar, fee) in TIP_BARS.items():
            bar_count, amount = divmod(amount, value)
            bars.extend([(bar, fee)] * bar_count)
        return bars

    async def _get_gold_amount(self, highrise) -> int:
        wallet = await highrise.get_wallet()
        return sum(
            currency.amount
            for currency in wallet.content
            if currency.type == "gold"
        )

    def get_top_tippers(self):
        sorted_tippers = sorted(
            self.tip_data.items(),
            key=lambda item: item[1]["total_tips"],
            reverse=True,
        )
        return sorted_tippers[:10]

    def get_user_tip_amount(self, username: str) -> int | None:
        for user_data in self.tip_data.values():
            if user_data["username"].lower() == username.lower():
                return user_data["total_tips"]
        return None

    def _load_tip_data(self) -> dict:
        return load_json(self.data_file)["users"]

    def _write_tip_data(self, user: User, tip: int) -> None:
        data = load_json(self.data_file)
        user_data = data["users"].get(
            user.id, {"total_tips": 0, "username": user.username}
        )
        user_data["total_tips"] += tip
        user_data["username"] = user.username
        data["users"][user.id] = user_data
        save_json(self.data_file, data)