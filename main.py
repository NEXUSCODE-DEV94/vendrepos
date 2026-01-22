import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import datetime
import os
import re
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

ADMIN_LOG_CHANNEL_ID = 1463501873586634782
PURCHASE_LOG_CHANNEL_ID = 1463426467957440603
MENTION_ROLE_ID = 1459385479026966661
CUSTOMER_ROLE_ID = 1319214442537422878
INVITE_LINK = "https://discord.gg/9WrjmX5Rw9"
TARGET_CHANNEL_IDS = [1463458889831026739, 1463426467957440603]

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

async def update_all_stats(bot):
    for channel_id in TARGET_CHANNEL_IDS:
        channel = bot.get_channel(channel_id)
        if not channel: continue
        try:
            count = 0
            async for _ in channel.history(limit=None):
                count += 1
            current_name = channel.name
            if "《" in current_name and "》" in current_name:
                new_name = re.sub(r"《.*?》", f"《{count}》", current_name)
                if current_name != new_name:
                    await channel.edit(name=new_name)
        except:
            pass

class CancelModal(discord.ui.Modal, title='キャンセル理由の入力'):
    reason = discord.ui.TextInput(
        label='キャンセル理由',
        style=discord.TextStyle.paragraph,
        placeholder='在庫切れのため、等',
        required=True
    )

    def __init__(self, buyer_id, item_name, admin_msg):
        super().__init__()
        self.buyer_id = buyer_id
        self.item_name = item_name
        self.admin_msg = admin_msg

    async def on_submit(self, interaction: discord.Interaction):
        try:
            buyer = await interaction.client.fetch_user(self.buyer_id)
            embed = discord.Embed(title="注文キャンセルのお知らせ", color=discord.Color.red())
            embed.description = f"申し訳ありません。以下の注文はキャンセルされました。\n\n**商品名:** {self.item_name}\n**理由:** {self.reason.value}"
            await buyer.send(embed=embed)
            
            new_embed = self.admin_msg.embeds[0]
            new_embed.title = "【キャンセル済み】" + new_embed.title
            new_embed.color = discord.Color.default()
            await self.admin_msg.edit(embed=new_embed, view=None)
            
            await interaction.response.send_message(f"注文をキャンセルし、ボタンを削除しました。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"エラー: {e}", ephemeral=True)

class PayPayModal(discord.ui.Modal, title='PayPay決済'):
    paypay_link = discord.ui.TextInput(
        label='PayPayリンクを入力してください',
        placeholder='https://pay.paypay.ne.jp/...',
        min_length=20,
        max_length=41,
        required=True
    )

    def __init__(self, item_name, price, item_data):
        super().__init__()
        self.item_name = item_name
        self.price = price
        self.item_data = item_data

    async def on_submit(self, interaction: discord.Interaction):
        if not self.paypay_link.value.startswith("https://pay.paypay.ne.jp/"):
            await interaction.response.send_message("無効なリンクです。", ephemeral=True)
            return

        admin_channel = interaction.client.get_channel(ADMIN_LOG_CHANNEL_ID)
        if not admin_channel:
            await interaction.response.send_message("管理用チャンネルが見つかりません。", ephemeral=True)
            return

        embed = discord.Embed(title="半自販機: 購入リクエスト", color=discord.Color.green())
        embed.description = "__商品の値段とPayPayの金額がちゃんとあっているか確かめてください__"
        embed.add_field(name="購入者", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.add_field(name="商品名", value=f"**{self.item_name}**", inline=True)
        embed.add_field(name="個数", value="**1個**", inline=True)
        embed.add_field(name="サーバー", value=f"**{interaction.guild.name} ({interaction.guild.id})**", inline=False)
        embed.add_field(name="PayPayリンク", value=self.paypay_link.value, inline=False)
        
        item_url = self.item_data.get("url", "情報なし")
        embed.add_field(name="在庫データ(URL)", value=f"||{item_url}||", inline=False)
        
        now = datetime.datetime.now().strftime('%Y/%m/%d %H:%M')
        embed.set_footer(text=now)

        view = AdminControlView()
        mention_text = f"<@&{MENTION_ROLE_ID}>" if MENTION_ROLE_ID else ""
        await admin_channel.send(content=mention_text, embed=embed, view=view)
        await interaction.response.send_message(embed=discord.Embed(description="### 購入をリクエストしました。", color=discord.Color.green()), ephemeral=True)

class AdminControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.is_received = False

    @discord.ui.button(label="受け取り完了", style=discord.ButtonStyle.green, custom_id="admin_receive_persist")
    async def confirm_receive(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.is_received = True
        button.disabled = True
        button.label = "支払い受取済み"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="商品を配達", style=discord.ButtonStyle.blurple, custom_id="admin_deliver_persist")
    async def deliver_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_received:
            await interaction.response.send_message("先に「受け取り完了」を押してください。", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        buyer_id = int(re.search(r"\((\.?[0-9]+)\)", embed.fields[0].value).group(1))
        item_name = embed.fields[1].value.replace("*", "")
        item_url = embed.fields[5].value.replace("|", "")

        await interaction.response.defer(ephemeral=True)

        try:
            buyer = await interaction.client.fetch_user(buyer_id)
            now = datetime.datetime.now().strftime('%y/%m/%d/ %H:%M:%S')
            
            dm_embed = discord.Embed(title=f"**{item_name}**", color=discord.Color.green())
            dm_embed.description = f"購入日\n```{now}```\n**購入サーバー**\n```Cats shop\n({interaction.guild.id})```"
            dm_embed.add_field(name="**商品名**", value=f"```{item_name}```", inline=False)
            dm_embed.add_field(name="**購入数**", value="```1個```", inline=True)

            dm_view = discord.ui.View()
            dm_view.add_item(discord.ui.Button(label="サーバーへ移動する", url=INVITE_LINK, style=discord.ButtonStyle.link))

            await buyer.send(embed=dm_embed, view=dm_view)
            await buyer.send(content=f"**在庫内容:**\n{item_url}")

            log_channel = interaction.client.get_channel(PURCHASE_LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(color=discord.Color.blue())
                log_embed.description = f"**商品名** **個数** **購入サーバー**\n```{item_name}``` ```1個``` ```{interaction.guild.name} ({interaction.guild.id})```\n**購入者**\n{buyer.mention} ({buyer.id})"
                await log_channel.send(embed=log_embed)
                await update_all_stats(interaction.client)

            role = interaction.guild.get_role(CUSTOMER_ROLE_ID)
            member = interaction.guild.get_member(buyer_id)
            if role and member:
                await member.add_roles(role)

            new_embed = embed
            new_embed.title = "【配達完了】" + new_embed.title
            new_embed.color = discord.Color.blue()
            await interaction.message.edit(embed=new_embed, view=None)
            await interaction.followup.send("配達完了メッセージを送信し、ボタンを削除しました。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラー: {e}", ephemeral=True)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.danger, custom_id="admin_cancel_persist")
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        buyer_id = int(re.search(r"\((\.?[0-9]+)\)", embed.fields[0].value).group(1))
        item_name = embed.fields[1].value.replace("*", "")
        await interaction.response.send_modal(CancelModal(buyer_id, item_name, interaction.message))

class ConfirmView(discord.ui.View):
    def __init__(self, item_name, price, item_data):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.price = price
        self.item_data = item_data

    @discord.ui.button(label="購入を確定", style=discord.ButtonStyle.green, custom_id="confirm_purchase_persist")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PayPayModal(self.item_name, self.price, self.item_data))

class ItemSelectView(discord.ui.View):
    def __init__(self, items_dict):
        super().__init__(timeout=None)
        self.items_dict = items_dict
        options = []
        fixed_emoji = "<a:win11:1463441603057422419>"
        for name, data in items_dict.items():
            options.append(discord.SelectOption(label=name, description=f"価格: {data['price']}円 ¦ 在庫 ∞", emoji=fixed_emoji))
        self.select = discord.ui.Select(placeholder="ここをタップして商品を選択", options=options, custom_id="item_select_persist")
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        selected_name = self.select.values[0]
        item_data = self.items_dict[selected_name]
        price = item_data['price']
        embed = discord.Embed(color=discord.Color.green())
        embed.description = (
            f"# 購入確認\n\n**商品名:** **{selected_name}**\n**個数** 1個\n**金額:** {price}円\n\n"
            f"**__⚠️ <@1463430104150573209> からのDMを許可していないと商品が受け取れない可能性があります__**"
        )
        await interaction.response.send_message(embed=embed, view=ConfirmView(selected_name, price, item_data), ephemeral=True)

class PanelView(discord.ui.View):
    def __init__(self, items=None):
        super().__init__(timeout=None)
        self.items = items

    @discord.ui.button(label="購入", style=discord.ButtonStyle.green, custom_id="panel_purchase_btn_persist")
    async def purchase_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.items is None:
            if os.path.exists("items.json"):
                with open("items.json", "r", encoding="utf-8") as f:
                    self.items = json.load(f)
        embed = discord.Embed(description="### 購入する商品を選択してください。", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, view=ItemSelectView(self.items), ephemeral=True)

class VendingBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        self.add_view(PanelView())
        self.add_view(AdminControlView())
        self.update_channel_stats.start()
        await self.tree.sync()

    @tasks.loop(seconds=200)
    async def update_channel_stats(self):
        await update_all_stats(self)

bot = VendingBot()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.competing, name="Cats Shop🛒"))
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="vending-panel", description="半自販機パネルを設置します")
async def vending_panel(interaction: discord.Interaction):
    await interaction.response.send_message("elminalでおけた", ephemeral=True)
    if not os.path.exists("items.json"):
        await interaction.followup.send("Error: items.jsonが見つかりません。", ephemeral=True)
        return
    with open("items.json", "r", encoding="utf-8") as f:
        items = json.load(f)
    embed = discord.Embed(title="R18 半自販機パネル", description="購入したい商品を下のメニューから選択してください。", color=discord.Color.green())
    for name, data in items.items():
        price = data.get("price", 0)
        embed.add_field(name=f"**{name}**", value=f"```価格: {price}円```", inline=False)
    embed.set_footer(text="Made by @4bc6")
    await interaction.channel.send(embed=embed, view=PanelView(items))

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
