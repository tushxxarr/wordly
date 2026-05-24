import os
import random
import asyncio
import json
import requests
from aiohttp import web
from telegram import Update, ChatMember, ChatMemberUpdated
from telegram.ext import (
   Application,
   CommandHandler,
   MessageHandler,
   ChatMemberHandler,
   ContextTypes,
   filters,
)

# ------------------------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# ------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
LOG_CHANNEL = os.environ.get("LOG_CHANNEL", "-100YOUR_LOG_CHANNEL_ID")
SUDO_USERS = [int(x) for x in os.environ.get("SUDO_USERS", "123456789").split(",")]
PORT = int(os.environ.get("PORT", "8080"))

# ------------------------------------------------------------------------
# GAME ENGINE & DICTIONARY
# ------------------------------------------------------------------------
print("Downloading English Dictionary...")
# Fetches ~370k English words for validation
WORD_URL = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
try:
   response = requests.get(WORD_URL)
   ENGLISH_DICTIONARY = set(response.text.splitlines())
   print(f"Successfully loaded {len(ENGLISH_DICTIONARY)} words!")
except Exception as e:
   print(f"Error loading dictionary: {e}")
   ENGLISH_DICTIONARY = set()

# In-memory storage for active games and group tracking
active_games = {}
GROUPS_FILE = "groups.json"

def load_groups():
   if os.path.exists(GROUPS_FILE):
       with open(GROUPS_FILE, "r") as f:
           return json.load(f)
   return []

def save_group(chat_id):
   groups = load_groups()
   if chat_id not in groups:
       groups.append(chat_id)
       with open(GROUPS_FILE, "w") as f:
           json.dump(groups, f)

class WordlyGame:
   def __init__(self, chat_id):
       self.chat_id = chat_id
       self.letters = self.generate_letters()
       self.found_words = set()
       self.scores = {}  # user_id: score
       self.users = {}   # user_id: first_name
       self.longest_word = ""
       self.longest_word_user = ""
       self.max_words = 20

   def generate_letters(self):
       vowels = "AEIOU"
       consonants = "BCDFGHJKLMNPQRSTVWXYZ"
       # Ensure a good mix of letters to make it playable
       chosen_vowels = random.choices(vowels, k=3)
       chosen_consonants = random.choices(consonants, k=6)
       all_letters = chosen_vowels + chosen_consonants
       random.shuffle(all_letters)
       return "".join(all_letters)

   def calculate_points(self, word):
       l = len(word)
       if l == 3: return 1
       if l == 4: return 2
       if l == 5: return 3
       if l == 6: return 5
       if l == 7: return 7
       if l >= 8: return 10
       return 0

# ------------------------------------------------------------------------
# RENDER.COM ANTI-SLEEP WEB SERVER
# ------------------------------------------------------------------------
async def web_server_handler(request):
   return web.Response(text="Wordly Bot is Online and Healthy! 🚀")

async def start_web_server():
   app = web.Application()
   app.router.add_get('/', web_server_handler)
   runner = web.AppRunner(app)
   await runner.setup()
   site = web.TCPSite(runner, '0.0.0.0', PORT)
   await site.start()
   print(f"Web server started on port {PORT}")

# ------------------------------------------------------------------------
# BOT COMMANDS & LOGIC
# ------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user = update.effective_user
   chat = update.effective_chat
   
   welcome_msg = (
       "🎉 **Welcome to Wordly Bot!** 🧠✨\n\n"
       "An addictive word-guess game where you create words using the given letters 📚🔡\n\n"
       "🎮 `/new` — Start a game and challenge yourself\n"
       "📖 `/help` — View all available commands and how to play\n\n"
       "🚀 Sharpen your vocabulary, think fast, and climb the leaderboard! 🏆🔥"
   )
   await update.message.reply_text(welcome_msg, parse_mode="Markdown")

   # Sudo Logging
   if chat.type == 'private' and str(LOG_CHANNEL) != "-100YOUR_LOG_CHANNEL_ID":
       log_msg = f"👤 **New User Started Bot**\nName: {user.first_name}\nID: `{user.id}`\nUsername: @{user.username}"
       try:
           await context.bot.send_message(chat_id=LOG_CHANNEL, text=log_msg, parse_mode="Markdown")
       except Exception as e:
           print(f"Log Error: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
   help_text = (
       "🔖 **How to Play**\n"
       "━━━━━━━━━━━━━━━━━━\n"
       "🔹 Send `/new` to start a round.\n"
       "🔹 Create valid English words using the letters provided.\n"
       "🔹 Words must be between 3 to 12 letters long.\n"
       "🔹 **Pro Tip:** Letter repetition is completely allowed!\n\n"
       "⚽️ **Points System**\n"
       "━━━━━━━━━━━━━━━━━━\n"
       "*We use a Progressive Curve scoring system to keep gameplay fair and rewarding. The longer the word, the bigger the payout!*\n\n"
       "🔸 3 letters: 1 point\n"
       "🔸 4 letters: 2 points\n"
       "🔸 5 letters: 3 points\n"
       "🔸 6 letters: 5 points\n"
       "🔸 7 letters: 7 points\n"
       "🎯 8 to 12 letters: 10 points (Max reward)"
   )
   await update.message.reply_text(help_text, parse_mode="Markdown")

async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   
   if chat_id in active_games and active_games[chat_id] is not None:
       await update.message.reply_text("⚠️ A game is already in progress! Finish it first.")
       return

   game = WordlyGame(chat_id)
   active_games[chat_id] = game
   spaced_letters = " ".join(game.letters)

   game_msg = (
       f"🔡 **{spaced_letters}**\n\n"
       f"Total words found: 0/{game.max_words}"
   )
   await update.message.reply_text(game_msg, parse_mode="Markdown")
   save_group(chat_id)

async def check_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   if chat_id not in active_games or active_games[chat_id] is None:
       return

   game = active_games[chat_id]
   word = update.message.text.upper()
   user = update.effective_user

   # 1. Check length
   if len(word) < 3 or len(word) > 12:
       return

   # 2. Check if it's already found
   if word in game.found_words:
       return

   # 3. Check if all characters belong to the given letters
   allowed_chars = set(game.letters)
   for char in word:
       if char not in allowed_chars:
           return

   # 4. Check dictionary
   if word.lower() not in ENGLISH_DICTIONARY:
       return

   # Word is Valid!
   game.found_words.add(word)
   points = game.calculate_points(word)
   
   game.scores[user.id] = game.scores.get(user.id, 0) + points
   game.users[user.id] = user.first_name

   if len(word) > len(game.longest_word):
       game.longest_word = word
       game.longest_word_user = user.first_name

   reply_msg = (
       f"👤 {user.first_name} found \"{word.capitalize()}\"\n"
       f"+{points} 💎\n\n"
       f"🔡 **{' '.join(game.letters)}**\n\n"
       f"Total words found: {len(game.found_words)}/{game.max_words}"
   )
   await update.message.reply_text(reply_msg, parse_mode="Markdown")

   # End Game Logic
   if len(game.found_words) >= game.max_words:
       await end_game(update, context, chat_id)

async def end_game(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id):
   game = active_games[chat_id]
   active_games[chat_id] = None

   if not game.scores:
       await context.bot.send_message(chat_id, "🎉 **Game over** 🎉\n\nNobody scored any points! 😢\n\n`/new` - Start new game", parse_mode="Markdown")
       return

   # Sort scores descending
   sorted_scores = sorted(game.scores.items(), key=lambda item: item[1], reverse=True)
   
   leaderboard = "🎉 **Game over** 🎉\n\n🏆 **Scores**\n\n"
   for idx, (uid, score) in enumerate(sorted_scores, 1):
       leaderboard += f"{idx}. {game.users[uid]} - {score} points 💎\n"

   leaderboard += f"\nLongest words:\n{game.longest_word.capitalize()} - {game.longest_word_user}\n\n`/new` - Start new game"
   
   await context.bot.send_message(chat_id, leaderboard, parse_mode="Markdown")

# ------------------------------------------------------------------------
# SUDO & LOGGING HANDLERS
# ------------------------------------------------------------------------
async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Logs when the bot is added to a group or promoted to admin."""
   result = update.my_chat_member
   if not result:
       return
   
   chat = result.chat
   new_status = result.new_chat_member.status
   old_status = result.old_chat_member.status
   user = result.from_user

   # Bot promoted to Admin
   if new_status == ChatMember.ADMINISTRATOR and old_status != ChatMember.ADMINISTRATOR:
       try:
           invite_link = await context.bot.export_chat_invite_link(chat.id)
           members_count = await context.bot.get_chat_member_count(chat.id)
           log_msg = (
               f"🚨 **Bot Promoted to Admin!**\n\n"
               f"**Group:** {chat.title}\n"
               f"**Group ID:** `{chat.id}`\n"
               f"**Members:** {members_count}\n"
               f"**Promoted by:** {user.first_name} (`{user.id}`)\n"
               f"**Invite Link:** {invite_link}"
           )
           await context.bot.send_message(chat_id=LOG_CHANNEL, text=log_msg, parse_mode="Markdown", disable_web_page_preview=True)
           save_group(chat.id)
       except Exception as e:
           print(f"Log Error: {e}")

async def log_private_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Forwards private messages to the log channel."""
   if update.effective_chat.type == 'private' and update.message.text and not update.message.text.startswith('/'):
       user = update.effective_user
       log_msg = f"📩 **Private Message**\nFrom: {user.first_name} (`{user.id}`)\n\n{update.message.text}"
       try:
           await context.bot.send_message(chat_id=LOG_CHANNEL, text=log_msg, parse_mode="Markdown")
       except Exception as e:
           print(f"Failed to log PM: {e}")

async def sudo_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Allows Sudo users to broadcast a message to all saved groups."""
   user_id = update.effective_user.id
   if user_id not in SUDO_USERS:
       return

   text = update.message.text.split(' ', 1)
   if len(text) < 2:
       await update.message.reply_text("⚠️ Usage: `/broadcast <message>`", parse_mode="Markdown")
       return

   msg = text[1]
   groups = load_groups()
   sent = 0
   
   await update.message.reply_text(f"🚀 Broadcasting to {len(groups)} groups...")
   
   for group_id in groups:
       try:
           await context.bot.send_message(chat_id=group_id, text=f"📢 **Announcement**\n\n{msg}", parse_mode="Markdown")
           sent += 1
           await asyncio.sleep(0.5) # Prevent flood limits
       except Exception:
           pass # Group might have kicked the bot
           
   await update.message.reply_text(f"✅ Broadcast complete! Sent to {sent} groups.")

async def post_init(application: Application):
   """Starts the Render Anti-Sleep web server when the bot initializes."""
   asyncio.create_task(start_web_server())

# ------------------------------------------------------------------------
# MAIN EXECUTION
# ------------------------------------------------------------------------
def main():
   if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
       print("ERROR: BOT_TOKEN is missing! Please set it in your environment variables.")
       return

   application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

   # Commands
   application.add_handler(CommandHandler("start", start_command))
   application.add_handler(CommandHandler("help", help_command))
   application.add_handler(CommandHandler("new", new_game))
   application.add_handler(CommandHandler("broadcast", sudo_broadcast))

   # Event Trackers
   application.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
   
   # Text Handlers (Game processing and PM logging)
   application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, check_word))
   application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, log_private_messages))

   print("🚀 Wordly Bot is now running...")
   application.run_polling()

if __name__ == "__main__":
   main()
