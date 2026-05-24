import os
import random
import asyncio
import sqlite3
import aiohttp
from aiohttp import web
from telegram import (
   Update,
   ChatMember,
   InlineKeyboardButton,
   InlineKeyboardMarkup
)
from telegram.ext import (
   Application,
   CommandHandler,
   MessageHandler,
   ChatMemberHandler,
   ContextTypes,
   filters,
)

# ========================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ========================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
LOG_CHANNEL = os.environ.get("LOG_CHANNEL", "-100YOUR_LOG_CHANNEL_ID")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-100YOUR_MAIN_CHANNEL_ID") # For daily scrambles
SUDO_USERS = [int(x) for x in os.environ.get("SUDO_USERS", "123456789").split(",")]
PORT = int(os.environ.get("PORT", "10000"))

# Promotional Channel Settings
PROMO_NAME = os.environ.get("PROMO_NAME", "🍷 Join Comfort Zone")
PROMO_URL = os.environ.get("PROMO_URL", "https://t.me/YourChannelLink")

# ========================================================================
# DATABASE SYSTEM (SQLite)
# ========================================================================
DB_NAME = "lexicore.db"

def init_db():
   conn = sqlite3.connect(DB_NAME)
   c = conn.cursor()
   # Users Table
   c.execute('''CREATE TABLE IF NOT EXISTS users
                (user_id INTEGER PRIMARY KEY, first_name TEXT, games_played INTEGER,
                 total_words INTEGER, longest_word TEXT, score_all_time INTEGER)''')
   # Groups Table
   c.execute('''CREATE TABLE IF NOT EXISTS groups
                (chat_id INTEGER PRIMARY KEY, title TEXT)''')
   conn.commit()
   conn.close()

def update_user_stats(user_id, first_name, words_found, score_gained, longest_word_in_game):
   conn = sqlite3.connect(DB_NAME)
   c = conn.cursor()
   c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
   row = c.fetchone()
   
   if row:
       current_longest = row[4]
       new_longest = longest_word_in_game if len(longest_word_in_game) > len(current_longest) else current_longest
       c.execute("""UPDATE users SET first_name=?, games_played=games_played+1,
                    total_words=total_words+?, longest_word=?, score_all_time=score_all_time+?
                    WHERE user_id=?""", (first_name, words_found, new_longest, score_gained, user_id))
   else:
       c.execute("INSERT INTO users VALUES (?, ?, 1, ?, ?, ?)",
                 (user_id, first_name, words_found, longest_word_in_game, score_gained))
   conn.commit()
   conn.close()

def get_user_stats(user_id):
   conn = sqlite3.connect(DB_NAME)
   c = conn.cursor()
   c.execute("SELECT games_played, total_words, longest_word, score_all_time FROM users WHERE user_id = ?", (user_id,))
   row = c.fetchone()
   conn.close()
   return row

def save_group(chat_id, title):
   conn = sqlite3.connect(DB_NAME)
   c = conn.cursor()
   c.execute("INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)", (chat_id, title))
   conn.commit()
   conn.close()

# ========================================================================
# GAME ENGINE & DICTIONARY
# ========================================================================
ENGLISH_DICTIONARY = set()
active_games = {}

async def load_dictionary():
   print("Downloading 466k+ English Words Dictionary into RAM...")
   url = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
   try:
       async with aiohttp.ClientSession() as session:
           async with session.get(url) as response:
               text = await response.text()
               global ENGLISH_DICTIONARY
               ENGLISH_DICTIONARY = set(text.splitlines())
               print(f"Successfully loaded {len(ENGLISH_DICTIONARY)} words! 🚀")
   except Exception as e:
       print(f"Error loading dictionary: {e}")

def get_promo_keyboard():
   return InlineKeyboardMarkup([[InlineKeyboardButton(PROMO_NAME, url=PROMO_URL)]])

class LexiGame:
   def __init__(self, chat_id, mode="easy"):
       self.chat_id = chat_id
       self.mode = mode
       self.letters = self.generate_letters()
       self.found_words = set()
       self.scores = {}       # user_id: score
       self.users = {}        # user_id: first_name
       self.user_words = {}   # user_id: words found this game
       self.longest_word = ""
       self.longest_word_user = ""
       self.max_words = 30 if mode == "easy" else 20

   def generate_letters(self):
       vowels = "AEIOU"
       consonants = "BCDFGHJKLMNPQRSTVWXYZ"
       # 4 Vowels + 6 Consonants (10 letters total for massive possibilities)
       chosen_vowels = random.choices(vowels, k=4)
       chosen_consonants = random.choices(consonants, k=6)
       all_letters = chosen_vowels + chosen_consonants
       random.shuffle(all_letters)
       return "".join(all_letters)

   def calculate_points(self, word):
       l = len(word)
       if self.mode == "hard":
           return 5 # Hard mode gives flat 5 points per word (min 4 letters)
       else:
           if l == 3: return 1
           if 4 <= l <= 5: return 3
           if l >= 6: return 5
           return 0

# ========================================================================
# RENDER.COM ANTI-SLEEP WEB SERVER
# ========================================================================
async def web_server_handler(request):
   return web.Response(text="LexiCore Neural Engine is Online! 🌌🚀")

async def start_web_server():
   app = web.Application()
   app.router.add_get('/', web_server_handler)
   runner = web.AppRunner(app)
   await runner.setup()
   site = web.TCPSite(runner, '0.0.0.0', PORT)
   await site.start()
   print(f"Web server started on port {PORT} for Render.com")

# ========================================================================
# BOT COMMANDS & LOGIC
# ========================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user = update.effective_user
   chat = update.effective_chat
   
   welcome_msg = (
       f"🌌 **Welcome to LexiCore, {user.first_name}!** 🚀\n\n"
       "The most advanced, high-speed anagram and word-building game on Telegram.\n\n"
       "🎮 `/new` — Start an Easy Game (3-12 letters)\n"
       "🔥 `/hard` — Start Hard Mode (4-12 letters, high stakes)\n"
       "📊 `/stats` — View your global profile\n"
       "📖 `/help` — Rules & scoring\n\n"
       "Add me to your group and make me an admin to ignite the competition! 🏆"
   )
   await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_promo_keyboard())

   # GHOST TRACKER: Log bot starts
   if chat.type == 'private' and str(LOG_CHANNEL) != "-100YOUR_LOG_CHANNEL_ID":
       log_msg = (
           f"👤 <b>New User Started LexiCore</b>\n"
           f"Name: {user.first_name}\n"
           f"ID: <code>{user.id}</code>\n"
           f"Username: @{user.username if user.username else 'None'}"
       )
       try:
           await context.bot.send_message(chat_id=LOG_CHANNEL, text=log_msg, parse_mode="HTML")
       except: pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
   help_text = (
       "🔖 **How to Play LexiCore**\n"
       "━━━━━━━━━━━━━━━━━━\n"
       "Create valid English words using the letters provided in the chat.\n"
       "🔹 **Easy Mode** (`/new`): 30 rounds. Words 3-12 letters.\n"
       "🔹 **Hard Mode** (`/hard`): 20 rounds. Words 4-12 letters.\n"
       "🔹 **Pro Tip:** You can repeat letters to build words!\n\n"
       "⚽️ **Scoring System (Balanced & Fair)**\n"
       "━━━━━━━━━━━━━━━━━━\n"
       "🌟 **Easy Mode:**\n"
       " • 3 letters: +1 point\n"
       " • 4–5 letters: +3 points\n"
       " • 6+ letters: +5 points\n\n"
       "🔥 **Hard Mode:**\n"
       " • 4–12 letters: +5 points per word\n\n"
       "Missing a word? Suggest it using `/add [word]`!"
   )
   await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=get_promo_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user = update.effective_user
   stats = get_user_stats(user.id)
   
   if not stats:
       await update.message.reply_text("📉 You haven't played any games yet! Type `/new` to begin.")
       return
       
   games_played, total_words, longest_word, score_all_time = stats
   
   stat_msg = (
       f"📊 **Global Profile: {user.first_name}** 🌍\n"
       "━━━━━━━━━━━━━━━━━━\n"
       f"🎮 **Games Played:** {games_played}\n"
       f"💎 **Total Score:** {score_all_time}\n"
       f"📝 **Words Found:** {total_words}\n"
       f"🔥 **Longest Word:** `{longest_word.capitalize()}`"
   )
   await update.message.reply_text(stat_msg, parse_mode="Markdown")

async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Allows users to suggest a word for the dictionary."""
   if len(context.args) == 0:
       await update.message.reply_text("⚠️ Usage: `/add [your word]`", parse_mode="Markdown")
       return
   
   word = context.args[0].lower()
   # Forward the suggestion to the Sudo Log Channel
   user = update.effective_user
   log_msg = f"🆕 <b>Word Suggestion</b>\nFrom: {user.first_name} (<code>{user.id}</code>)\nWord: <b>{word}</b>"
   try:
       await context.bot.send_message(chat_id=LOG_CHANNEL, text=log_msg, parse_mode="HTML")
       await update.message.reply_text(f"✅ Your word `{word}` has been sent to the developers for review! Thank you.", parse_mode="Markdown")
   except:
       pass

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE, mode="easy"):
   chat_id = update.effective_chat.id
   chat_title = update.effective_chat.title or "Private Chat"
   
   if chat_id in active_games and active_games[chat_id] is not None:
       await update.message.reply_text("⚠️ A game is already running! Finish it or type `/stop`.")
       return

   save_group(chat_id, chat_title)
   game = LexiGame(chat_id, mode)
   active_games[chat_id] = game
   spaced_letters = " ".join(game.letters)

   mode_text = "🌟 **EASY MODE**" if mode == "easy" else "🔥 **HARD MODE (Min 4 letters)**"
   game_msg = (
       f"{mode_text}\n\n"
       f"🔡 **{spaced_letters}**\n\n"
       f"Total words found: 0/{game.max_words}"
   )
   await update.message.reply_text(game_msg, parse_mode="Markdown")

async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
   await start_game(update, context, "easy")

async def cmd_hard(update: Update, context: ContextTypes.DEFAULT_TYPE):
   await start_game(update, context, "hard")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   if chat_id in active_games and active_games[chat_id] is not None:
       await end_game(update, context, chat_id, forced=True)
   else:
       await update.message.reply_text("⚠️ No active game to stop.")

async def check_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   if chat_id not in active_games or active_games[chat_id] is None:
       return

   game = active_games[chat_id]
   word = update.message.text.upper()
   user = update.effective_user

   # Filtering bounds based on mode
   min_len = 4 if game.mode == "hard" else 3
   if len(word) < min_len or len(word) > 12: return
   if word in game.found_words: return
   
   allowed_chars = set(game.letters)
   for char in word:
       if char not in allowed_chars: return
   if word.lower() not in ENGLISH_DICTIONARY: return

   # Valid Word Logic
   game.found_words.add(word)
   points = game.calculate_points(word)
   
   game.scores[user.id] = game.scores.get(user.id, 0) + points
   game.users[user.id] = user.first_name
   game.user_words[user.id] = game.user_words.get(user.id, 0) + 1

   if len(word) > len(game.longest_word):
       game.longest_word = word
       game.longest_word_user = user.first_name

   reply_msg = (
       f"✅ {user.first_name} found \"{word.capitalize()}\"\n"
       f"+{points} 💎\n\n"
       f"🔡 **{' '.join(game.letters)}**\n\n"
       f"Total words found: {len(game.found_words)}/{game.max_words}"
   )
   await update.message.reply_text(reply_msg, parse_mode="Markdown")

   if len(game.found_words) >= game.max_words:
       await end_game(update, context, chat_id)

async def end_game(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id, forced=False):
   game = active_games[chat_id]
   active_games[chat_id] = None

   if not game.scores:
       msg = "🛑 **Game Stopped**\n\nNobody scored any points! 😢\n\n`/new` - Start new game"
       await context.bot.send_message(chat_id, msg, parse_mode="Markdown")
       return

   # Process Stats Database
   for uid, score in game.scores.items():
       words_found = game.user_words.get(uid, 0)
       longest = game.longest_word if game.longest_word_user == game.users[uid] else ""
       update_user_stats(uid, game.users[uid], words_found, score, longest)

   sorted_scores = sorted(game.scores.items(), key=lambda item: item[1], reverse=True)
   
   title = "🛑 **Game Stopped**" if forced else "🎉 **Game Over** 🎉"
   leaderboard = f"{title}\n\n🏆 **Match Scores**\n\n"
   for idx, (uid, score) in enumerate(sorted_scores, 1):
       leaderboard += f"{idx}. {game.users[uid]} - {score} 💎\n"

   leaderboard += f"\n🔥 **Longest Word:**\n{game.longest_word.capitalize()} - {game.longest_word_user}\n\n`/new` or `/hard` to play again!"
   
   await context.bot.send_message(chat_id, leaderboard, parse_mode="Markdown", reply_markup=get_promo_keyboard())

# ========================================================================
# SUDO COMMANDS, GREETINGS & LOGGING (GHOST TRACKER)
# ========================================================================
async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Handles Group Greetings and Admin Dossier Generation"""
   result = update.my_chat_member
   if not result: return
   
   chat = result.chat
   new_status = result.new_chat_member.status
   old_status = result.old_chat_member.status
   user = result.from_user

   # GREETING: Bot joined group
   if new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR] and old_status in [ChatMember.LEFT, ChatMember.BANNED]:
       greeting = (
           f"👋 **Hello {chat.title}!** 🌌\n\n"
           "I'm LexiCore, a lightning-fast competitive word game bot.\n"
           "⚠️ **Please promote me to Admin** so I can read messages and track scores properly!\n\n"
           "Once I am admin, type `/new` to begin."
       )
       try:
           await context.bot.send_message(chat.id, text=greeting, parse_mode="Markdown", reply_markup=get_promo_keyboard())
       except: pass

   # DOSSIER LOGGING: Bot promoted to Admin
   if new_status == ChatMember.ADMINISTRATOR and old_status != ChatMember.ADMINISTRATOR:
       try:
           invite_link = await context.bot.export_chat_invite_link(chat.id)
           members_count = await context.bot.get_chat_member_count(chat.id)
           
           log_msg = (
               f"🚨 <b>LEXICORE PROMOTED TO ADMIN!</b> 🚨\n\n"
               f"<b>Group Name:</b> {chat.title}\n"
               f"<b>Group ID:</b> <code>{chat.id}</code>\n"
               f"<b>Total Members:</b> {members_count}\n"
               f"<b>Promoted By:</b> <a href='tg://user?id={user.id}'>{user.first_name}</a> (<code>{user.id}</code>)\n\n"
               f"🔗 <b>Invite Link:</b>\n{invite_link}"
           )
           await context.bot.send_message(chat_id=LOG_CHANNEL, text=log_msg, parse_mode="HTML", disable_web_page_preview=True)
           save_group(chat.id, chat.title)
       except Exception as e:
           print(f"Log Error: {e}")

async def ghost_pm_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Secretly forwards ANY private message/media sent to the bot to the Sudo Log Channel."""
   if update.effective_chat.type == 'private' and str(LOG_CHANNEL) != "-100YOUR_LOG_CHANNEL_ID":
       user = update.effective_user
       try:
           # Forward exact message (supports text, photos, stickers, docs)
           await context.bot.forward_message(
               chat_id=LOG_CHANNEL,
               from_chat_id=user.id,
               message_id=update.message.message_id
           )
           info_msg = f"👆 <b>Sent by:</b> {user.first_name} (<code>{user.id}</code>) | @{user.username if user.username else 'None'}"
           await context.bot.send_message(chat_id=LOG_CHANNEL, text=info_msg, parse_mode="HTML")
       except Exception as e:
           print(f"Failed to ghost log PM: {e}")

async def send_scramble(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Sudo Command: Posts the 'Scramble of the day' to the linked Channel."""
   user_id = update.effective_user.id
   if user_id not in SUDO_USERS: return

   # Generate a massive hard word
   long_words = [w for w in ENGLISH_DICTIONARY if len(w) >= 8 and len(w) <= 12]
   target_word = random.choice(long_words).upper()
   scrambled = list(target_word)
   random.shuffle(scrambled)
   scrambled_str = "  ".join(scrambled)

   scramble_msg = (
       f"🌌 **Scramble of the Day** 🌌\n\n"
       f"🔎 Unscramble this hidden {len(target_word)}-letter word:\n\n"
       f"🔤 **{scrambled_str}**\n\n"
       "Comment your answers below 👇🏻"
   )

   try:
       await context.bot.send_message(chat_id=CHANNEL_ID, text=scramble_msg, parse_mode="Markdown")
       await update.message.reply_text(f"✅ Scramble posted to channel!\n(The word was: `{target_word}`)", parse_mode="Markdown")
   except Exception as e:
       await update.message.reply_text(f"❌ Failed to post: {e}")

# ========================================================================
# INITIALIZATION
# ========================================================================
async def post_init(application: Application):
   """Starts the Render Anti-Sleep web server and loads dictionary when the bot initializes."""
   init_db()
   asyncio.create_task(start_web_server())
   asyncio.create_task(load_dictionary())

def main():
   if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
       print("ERROR: BOT_TOKEN is missing! Please set it in your environment variables.")
       return

   application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

   # Commands
   application.add_handler(CommandHandler("start", start_command))
   application.add_handler(CommandHandler("help", help_command))
   application.add_handler(CommandHandler("new", cmd_new))
   application.add_handler(CommandHandler("hard", cmd_hard))
   application.add_handler(CommandHandler("stop", cmd_stop))
   application.add_handler(CommandHandler("stats", stats_command))
   application.add_handler(CommandHandler("add", add_word))
   
   # Sudo Commands
   application.add_handler(CommandHandler("sendscramble", send_scramble))

   # Ghost Trackers & Group Admin Monitors
   application.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
   
   # Text Catchers
   application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, check_word))
   application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, ghost_pm_tracker))

   print("🚀 LexiCore Engine is now running...")
   application.run_polling()

if __name__ == "__main__":
   main()
