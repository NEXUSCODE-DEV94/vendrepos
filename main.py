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
def home(): return "Bot is running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

async def update_all_stats(bot):
    for channel_id in TARGET_CHANNEL_IDS:
        channel = bot.get_channel(channel_id)
        if not channel: continue
        try:
            count = 0
            async for _ in channel.history(limit=None): count += 1
            current_name = channel.name
            if "《" in current_name and "》" in current_name:
                new_name = re.sub(r"《.*?》", f"《{count}》", current_name)
                if current_name != new_name: await channel.edit(name=new_name)
        except: pass

class CancelModal(discord.ui.Modal, title='キャンセル理由の入力'):
    reason = discord.ui.TextInput(label='キャンセル理由', style=discord.TextStyle.paragraph, placeholder='在庫切れのため、等', required=True)
    def __init__(self, buyer_id, item_name, admin_msg):
        super().__init__()
        self.buyer_id, self.item_name, self.admin_msg = buyer_id, item_name, admin_msg
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            buyer = await interaction.client.fetch_user(self.buyer_id)
            embed = discord.Embed(title="注文キャンセルのお知らせ", color=discord.Color.red())
            embed.description = f"申し訳ありません。以下の注文はキャンセルされました。\n\n**商品名:** {self.item_name}\n**理由:** {self.reason.value}"
            await buyer.send(embed=embed)
            new_embed = self.admin_msg.embeds[0]
            new_embed.title = "【キャンセル済み】" + (new_embed.title or "")
            new_embed.color = discord.Color.default()
            await self.admin_msg.edit(embed=new_embed, view=None)
            await interaction.followup.send("注文をキャンセルし、ボタンを削除しました。", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"エラー: {e}", ephemeral=True)

class PayPayModal(discord.ui.Modal, title='PayPay決済'):
    paypay_link = discord.ui.TextInput(label='PayPayリンクを入力してください', placeholder='https://pay.paypay.ne.jp/...', min_length=20, max_length=41, required=True)
    def __init__(self, item_name, price, item_data):
        super().__init__()
        self.item_name, self.price, self.item_data = item_name, price, item_data
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # 即座に応答
        if not self.paypay_link.value.startswith("https://pay.paypay.ne.jp/"):
            await interaction.followup.send("無効なリンクです。", ephemeral=True)
            return
        admin_channel = interaction.client.get_channel(ADMIN_LOG_CHANNEL_ID)
        if not admin_channel: return
        item_val = self.item_data.get("url") or self.item_data.get("link") or self.item_data.get("sites", "情報なし")
        embed = discord.Embed(title="半自販機: 購入リクエスト", color=discord.Color.green())
        embed.description = "__商品の値段とPayPayの金額がちゃんとあっているか確かめてください__"
        embed.add_field(name="購入者", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.add_field(name="**商品名**", value=f"**{self.item_name}**", inline=True)
        embed.add_field(name="**個数**", value="**1個**", inline=True)
        embed.add_field(name="**サーバー**", value=f"**{interaction.guild.name} ({interaction.guild.id})**", inline=False)
        embed.add_field(name="PayPayリンク", value=self.paypay_link.value, inline=False)
        embed.add_field(name="アイテムリンク", value=f"||{item_val}||", inline=False)
        embed.set_footer(text=datetime.datetime.now().strftime('%Y/%m/%d %H:%M'))
        mention = f"<@&{MENTION_ROLE_ID}>" if MENTION_ROLE_ID else ""
        await admin_channel.send(content=mention, embed=embed, view=AdminControlView())
        await interaction.followup.send(embed=discord.Embed(description="### 購入をリクエストしました。", color=discord.Color.green()), ephemeral=True)

class AdminControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.is_received = False
    @discord.ui.button(label="受け取り完了", style=discord.ButtonStyle.green, custom_id="admin_receive_persist")
    async def confirm_receive(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.is_received = True
        button.disabled, button.label = True, "支払い受取済み"
        await interaction.response.edit_message(view=self)
    @discord.ui.button(label="商品を配達", style=discord.ButtonStyle.blurple, custom_id="admin_deliver_persist")
    async def deliver_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not getattr(self, "is_received", False):
            await interaction.response.send_message("先に「受け取り完了」を押してください。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        embed = interaction.message.embeds[0]
        
        # フィールドから安全にデータを抽出
        buyer_id = int(re.search(r"\((\d+)\)", embed.fields[0].value).group(1))
        item_name = embed.fields[1].value.replace("*", "")
        # インデックスエラー対策：アイテムリンク（在庫）フィールドを名前で探す
        item_val = "情報なし"
        for field in embed.fields:
            if field.name == "アイテムリンク":
                item_val = field.value.replace("|", "")
                break

        try:
            buyer = await interaction.client.fetch_user(buyer_id)
            now = datetime.datetime.now().strftime('%y/%m/%d/ %H:%M:%S')
            dm = discord.Embed(title=f"**{item_name}**", color=discord.Color.green())
            dm.description = f"購入日\n```{now}```\n**購入サーバー**\n```Cats shop\n({interaction.guild.id})```"
            dm.add_field(name="**商品名**", value=f"```{item_name}```", inline=False)
            dm.add_field(name="**購入数**", value="```1個```", inline=True)
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="サーバーへ移動する", url=INVITE_LINK, style=discord.ButtonStyle.link))
            await buyer.send(embed=dm, view=view)
            await buyer.send(content=f"**在庫内容:**\n{item_val}")
            
            log = interaction.client.get_channel(PURCHASE_LOG_CHANNEL_ID)
            if log:
                le = discord.Embed(color=discord.Color.blue())
                le.description = f"**商品名** **個数** **購入サーバー**\n```{item_name}``` ```1個``` ```{interaction.guild.name} ({interaction.guild.id})```\n**購入者**\n{buyer.mention} ({buyer.id})"
                await log.send(embed=le)
            
            role = interaction.guild.get_role(CUSTOMER_ROLE_ID)
            member = interaction.guild.get_member(buyer_id)
            if role and member: await member.add_roles(role)
            
            embed.title = "【配達完了】" + (embed.title or "")
            embed.color = discord.Color.blue()
            await interaction.message.edit(embed=embed, view=None)
            await interaction.followup.send("配達完了メッセージを送信し、ボタンを削除しました。", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"エラー: {e}", ephemeral=True)

class ConfirmView(discord.ui.View):
    def __init__(self, item_name, price, item_data):
        super().__init__(timeout=None)
        self.item_name, self.price, self.item_data = item_name, price, item_data
    @discord.ui.button(label="購入を確定", style=discord.ButtonStyle.green, custom_id="confirm_purchase_persist")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Modalはdeferできないのでそのまま送る
        await interaction.response.send_modal(PayPayModal(self.item_name, self.price, self.item_data))

class ItemSelectView(discord.ui.View):
    def __init__(self, items_dict):
        super().__init__(timeout=None)
        self.items_dict = items_dict
        options = [discord.SelectOption(label=n, description=f"価格: {d['price']}円 ¦ 在庫 ∞", emoji="<a:win11:1463441603057422419>") for n, d in items_dict.items()]
        self.select = discord.ui.Select(placeholder="ここをタップして商品を選択", options=options, custom_id="item_select_persist")
        self.select.callback = self.select_callback
        self.add_item(self.select)
    async def select_callback(self, interaction: discord.Interaction):
        # 選択後のメッセージ送信も即座に行う
        name = self.select.values[0]
        data = self.items_dict[name]
        embed = discord.Embed(color=discord.Color.green())
        embed.description = f"# 購入確認\n\n**商品名:** **{name}**\n**個数** 1個\n**金額:** {data['price']}円\n\n**__⚠️ <@1463430104150573209> からのDMを許可していないと商品が受け取れない可能性があります__**"
        await interaction.response.send_message(embed=embed, view=ConfirmView(name, data['price'], data), ephemeral=True)

class PanelView(discord.ui.View):
    def __init__(self, items=None):
        super().__init__(timeout=None)
        self.items = items
    @discord.ui.button(label="購入", style=discord.ButtonStyle.green, custom_id="panel_purchase_btn_persist")
    async def purchase_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True) # 即座に応答して時間稼ぎ
        if self.items is None and os.path.exists("items.json"):
            with open("items.json", "r", encoding="utf-8") as f: self.items = json.load(f)
        embed = discord.Embed(description="### 購入する商品を選択してください。", color=discord.Color.green())
        await interaction.followup.send(embed=embed, view=ItemSelectView(self.items), ephemeral=True)

class VendingBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=discord.Intents.all())
    async def setup_hook(self):
        self.add_view(PanelView()); self.add_view(AdminControlView())
        self.update_channel_stats.start(); await self.tree.sync()
    @tasks.loop(seconds=200)
    async def update_channel_stats(self): await update_all_stats(self)

bot = VendingBot()

@bot.tree.command(name="vending-panel", description="設置")
async def vending_panel(interaction: discord.Interaction):
    # コマンドも即座に応答を返す
    await interaction.response.send_message("elminalでおけた", ephemeral=True)
    if not os.path.exists("items.json"): return
    with open("items.json", "r", encoding="utf-8") as f: items = json.load(f)
    embed = discord.Embed(title="R18 半自販機パネル", description="購入したい商品を下のメニューから選択してください。", color=discord.Color.green())
    for n, d in items.items(): embed.add_field(name=f"**{n}**", value=f"```価格: {d.get('price', 0)}円```", inline=False)
    embed.set_footer(text="Made by @4bc6")
    await interaction.channel.send(embed=embed, view=PanelView(items))

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
