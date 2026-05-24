import os
import random
import json
import asyncio
from aiohttp import web
import aiohttp
from telegram import Update, constants, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
   Application,
   CommandHandler,
   MessageHandler,
   ChatMemberHandler,
   ContextTypes,
   filters,
)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
LOG_GROUP_ID = os.environ.get("LOG_CHANNEL_ID")
if LOG_GROUP_ID:
   LOG_GROUP_ID = int(LOG_GROUP_ID)
PORT = int(os.environ.get("PORT", "10000"))

PROMO_NAME = os.environ.get("PROMO_NAME", "Join Us")
PROMO_LINK = os.environ.get("PROMO_URL", "https://t.me/YourChannel")

SUDO_USERS_STR = os.environ.get("SUDO_USERS", "")
SUDO_USERS = [int(x.strip()) for x in SUDO_USERS_STR.split(",")] if SUDO_USERS_STR else []

# ==============================================================================
# DICTIONARY ENGINE
# ==============================================================================
BASELINE_WORDS_URL = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
NEURAL_DICTIONARY = set()

async def load_neural_dictionary():
   """Downloads the dictionary in the background so it doesn't block Render startup."""
   print("Fetching Lexicore baseline dictionary...")
   try:
       async with aiohttp.ClientSession() as session:
           async with session.get(BASELINE_WORDS_URL) as response:
               if response.status == 200:
                   text = await response.text()
                   global NEURAL_DICTIONARY
                   NEURAL_DICTIONARY = set(text.splitlines())
                   print(f"Dictionary loaded: {len(NEURAL_DICTIONARY)} words.")
               else:
                   print(f"Dictionary download failed. Status: {response.status}")
   except Exception as e:
       print(f"Dictionary load error: {e}")

# ==============================================================================
# RENDER.COM ANTI-SLEEP WEB SERVER (MUST START INSTANTLY)
# ==============================================================================
async def web_server_handler(request):
   return web.Response(text="Lexicore Neural Word Engine is Operational 🌌🚀")

async def start_web_server():
   """Starts instantly to satisfy Render's port binding requirement."""
   app = web.Application()
   app.router.add_get('/', web_server_handler)
   runner = web.AppRunner(app)
   await runner.setup()
   site = web.TCPSite(runner, '0.0.0.0', PORT)
   await site.start()
   print(f"Anti-sleep web server listening on port {PORT}")

# ==============================================================================
# GAME LOGIC
# ==============================================================================
active_games = {}

class WordGame:
   def __init__(self, chat_id, mode="easy"):
       self.chat_id = chat_id
       self.mode = mode
       self.max_rounds = 15 if mode == "easy" else 20
       self.baseline_word = self.generate_baseline_word()
       self.scramble = self.generate_scramble()
       self.letters = set(self.baseline_word)
       self.found_words = set()
       self.scores = {}
       self.users = {}
       self.longest_word = ""
       self.longest_word_user = ""
       self.active = True

   def generate_baseline_word(self):
       hard_words = [w for w in NEURAL_DICTIONARY if 8 <= len(w) <= 12]
       return random.choice(hard_words).upper() if hard_words else "LEXICORE"

   def generate_scramble(self):
       scrambled_list = list(self.baseline_word)
       random.shuffle(scrambled_list)
       return "  ".join(scrambled_list)

   def calculate_points(self, word):
       l = len(word)
       if self.mode == "hard":
           return 5
       else:
           if l <= 3: return 1
           if l == 4: return 2
           if l == 5: return 3
           if l == 6: return 5
           if l == 7: return 7
           if l >= 8: return 10
           return 0

   def generate_result_message(self):
       sorted_scores = sorted(self.scores.items(), key=lambda item: item[1], reverse=True)
       results = "🎉 **Game Over** 🎉\n\n🏆 **Top Scores**\n\n"
       
       for idx, (uid, score) in enumerate(sorted_scores, 1):
           results += f"{idx}. {self.users[uid]} - **{score} 💎**\n"
           
       results += f"\n🔥 **Longest Word:**\n`{self.longest_word.capitalize()}` - {self.longest_word_user}\n"
       results += "\n`/new` or `/hard` to play again 🌌"
       
       return results

# ==============================================================================
# BOT COMMAND HANDLERS
# ==============================================================================
def get_promo_keyboard():
   return InlineKeyboardMarkup([[InlineKeyboardButton(PROMO_NAME, url=PROMO_LINK)]])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user = update.effective_user
   chat = update.effective_chat
   
   if chat.type == constants.ChatType.PRIVATE and LOG_GROUP_ID:
       text = f"👤 **New User in PM**\nName: {user.first_name}\nID: `{user.id}`\nUsername: @{user.username}"
       try:
           await context.bot.send_message(chat_id=LOG_GROUP_ID, text=text, parse_mode=constants.ParseMode.MARKDOWN)
       except Exception: pass

   welcome = (
       f"🌌 **Welcome to Lexicore, {user.first_name}!** 🌌\n\n"
       "The universe's fastest, most advanced anagram-scramble bot.\n\n"
       "🎮 `/new` — Begin Scramble Game (Easy Mode)\n"
       "💥 `/hard` — Begin Scramble Game (Hard Mode)\n"
       "📖 `/help` — Rules & Scoring\n\n"
       "Add me to your group and make me admin to ignite the competition! 🚀"
   )
   await update.message.reply_text(welcome, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=get_promo_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
   help_text = (
       "📖 **How to Master Lexicore**\n\n"
       "1. Start a game in groups using `/new` (Easy) or `/hard` (Hard).\n"
       "2. Make words using *only* the given scrambled letters.\n"
       "3. Repetition of letters is allowed.\n\n"
       "⚽  **Scoring System** ⚽\n"
       "━━━━━━━━━━━━━━━━━━\n"
       "🔸 3 letters: 1 point\n"
       "🔸 4 letters: 2 points\n"
       "🔸 5 letters: 3 points\n"
       "🔸 6 letters: 5 points\n"
       "🔸 7 letters: 7 points\n"
       "🎯 8 to 12 letters: 10 points\n\n"
       "Missing a word? Suggest it using `/add <word>`!"
   )
   await update.message.reply_text(help_text, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=get_promo_keyboard())

async def start_game_easy(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   if not NEURAL_DICTIONARY:
       await update.message.reply_text("⏳ Dictionary is still loading. Please try again in a few seconds.")
       return

   if chat_id in active_games and active_games[chat_id].active:
       await update.message.reply_text("⚠️ Scramble already in progress. Finish it or use `/stop`.")
       return
   
   active_games[chat_id] = WordGame(chat_id, mode="easy")
   game = active_games[chat_id]
   
   game_start_text = (
       f"🌌 **New Scramble: EASY MODE** 🌌\n\n"
       f"🔎 Make words using these letters:\n\n"
       f"🔤 ** {game.scramble} **\n\n"
       f"Bounds: 3-12 letters ✅\n"
       f"Find {game.max_rounds} words for results! 🎯"
   )
   await update.message.reply_text(game_start_text, parse_mode=constants.ParseMode.MARKDOWN)

async def start_game_hard(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   if not NEURAL_DICTIONARY:
       await update.message.reply_text("⏳ Dictionary is still loading. Please try again in a few seconds.")
       return

   if chat_id in active_games and active_games[chat_id].active:
       await update.message.reply_text("⚠️ Scramble already in progress. Finish it or use `/stop`.")
       return
   
   active_games[chat_id] = WordGame(chat_id, mode="hard")
   game = active_games[chat_id]
   
   game_start_text = (
       f"💥 **New Scramble: HARD MODE** 💥\n\n"
       f"🔎 Make words using these letters:\n\n"
       f"🔤 ** {game.scramble} **\n\n"
       f"Bounds: 4-12 letters (+5 pts each) ✅\n"
       f"Find {game.max_rounds} words for results! 🎯"
   )
   await update.message.reply_text(game_start_text, parse_mode=constants.ParseMode.MARKDOWN)

async def stop_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   if chat_id in active_games and active_games[chat_id].active:
       results = active_games[chat_id].generate_result_message()
       results = results.replace("🎉 **Game Over** 🎉", "🛑 **Sequence Aborted**")
       active_games[chat_id].active = False
       active_games[chat_id] = None
       await update.message.reply_text(results, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=get_promo_keyboard())
   else:
       await update.message.reply_text("⚠️ No active sequence to stop.")

# ==============================================================================
# GUESS HANDLER
# ==============================================================================
async def check_guesses(update: Update, context: ContextTypes.DEFAULT_TYPE):
   chat_id = update.effective_chat.id
   if chat_id not in active_games or not active_games[chat_id].active:
       return

   game = active_games[chat_id]
   guess = update.message.text.upper()
   user = update.effective_user
   
   min_len = 4 if game.mode == "hard" else 3
   if len(guess) < min_len or len(guess) > 12: return
   if guess in game.found_words: return
   
   allowed_chars = set(game.baseline_word)
   for char in guess:
       if char not in allowed_chars: return

   if guess.lower() not in NEURAL_DICTIONARY: return
   
   # GUESS ACCEPTED
   game.found_words.add(guess)
   points = game.calculate_points(guess)
   
   score_increment = f"+{points} 💎"
   results_update = (
       f"✅ {user.first_name} found `{guess.capitalize()}`!\n"
       f"{score_increment}\n\n"
       f"Find {game.max_rounds - len(game.found_words)} more!"
   )
   await update.message.reply_text(results_update, parse_mode=constants.ParseMode.MARKDOWN)
   
   # Stats update
   game.scores[user.id] = game.scores.get(user.id, 0) + points
   game.users[user.id] = user.first_name
   if len(guess) > len(game.longest_word):
       game.longest_word = guess
       game.longest_word_user = user.first_name

   # End game
   if len(game.found_words) >= game.max_rounds:
       results = game.generate_result_message()
       game.active = False
       await context.bot.send_message(chat_id, text=results, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=get_promo_keyboard())
       active_games[chat_id] = None

# ==============================================================================
# GHOST LOGGING & ADMIN ALERTS
# ==============================================================================
async def log_private_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Forwards PMs to Log Group."""
   user = update.effective_user
   chat = update.effective_chat
   if chat.type != constants.ChatType.PRIVATE or not update.message or not LOG_GROUP_ID:
       return
   
   try:
       await context.bot.forward_message(chat_id=LOG_GROUP_ID, from_chat_id=user.id, message_id=update.message.message_id)
       info_text = f"📩 **PM Forward**\nFrom: {user.first_name} (`{user.id}`)\nUsername: @{user.username if user.username else 'None'}"
       await context.bot.send_message(chat_id=LOG_GROUP_ID, text=info_text, parse_mode=constants.ParseMode.MARKDOWN)
   except Exception: pass

async def log_joining_groups_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """Logs when bot is made admin."""
   result = update.my_chat_member
   if not result: return
   
   chat = result.chat
   new_status = result.new_chat_member.status
   old_status = result.old_chat_member.status
   promoted_by = result.from_user

   # GREETING
   if new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR] and old_status in [ChatMember.LEFT, ChatMember.BANNED]:
       welcome = (
           f"👋 **Lexicore joined {chat.title}!** 🌌\n\n"
           "⚠️ **Please promote me to Admin** so I can read guesses and update results.\n\n"
           "Once promoted, use `/new` or `/hard` to begin."
       )
       try:
           await context.bot.send_message(chat_id=chat.id, text=welcome, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=get_promo_keyboard())
       except: pass

   # ADMIN DOSSIER
   if new_status == ChatMember.ADMINISTRATOR and old_status != ChatMember.ADMINISTRATOR and LOG_GROUP_ID:
       try:
           member_count = await chat.get_member_count()
           invite_link = await chat.export_invite_link()
           log_text = (
               f"🚨 **NEW GROUP ADMIN DOSSIER** 🚨\n\n"
               f"**Group:** {chat.title}\n"
               f"**Group ID:** `{chat.id}`\n"
               f"**Members:** {member_count}\n"
               f"**Join Link:** {invite_link}\n"
               f"**Promoted By:** @{promoted_by.username} (`{promoted_by.id}`)"
           )
           await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_text, parse_mode=constants.ParseMode.MARKDOWN, disable_web_page_preview=True)
       except Exception: pass

# ==============================================================================
# SUDO COMMANDS
# ==============================================================================
async def sudo_only_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user = update.effective_user
   command_text = update.message.text

   if command_text.startswith('/add'):
       args = context.args
       if len(args) == 0:
           await update.message.reply_text("⚠️ Usage: `/add <word>`")
           return
       
       suggested_word = args[0].lower()
       if LOG_GROUP_ID:
           log_text = f"🆕 **Word Suggestion**\nWord: `{suggested_word}`\nBy: @{user.username} (`{user.id}`)"
           await context.bot.send_message(chat_id=LOG_GROUP_ID, text=log_text, parse_mode=constants.ParseMode.MARKDOWN)
       await update.message.reply_text(f"✅ Suggestion for `{suggested_word}` submitted for review.")

# ==============================================================================
# INITIALIZATION
# ==============================================================================
async def start_tasks(application: Application):
   """Start the web server immediately, then load the dictionary."""
   asyncio.create_task(start_web_server())
   asyncio.create_task(load_neural_dictionary())

def main():
   if not BOT_TOKEN:
       print("ERROR: BOT_TOKEN is missing!")
       return

   application = Application.builder().token(BOT_TOKEN).post_init(start_tasks).build()

   # Commands
   application.add_handler(CommandHandler("start", start_command))
   application.add_handler(CommandHandler("help", help_command))
   application.add_handler(CommandHandler("new", start_game_easy))
   application.add_handler(CommandHandler("hard", start_game_hard))
   application.add_handler(CommandHandler("stop", stop_game))
   
   # Sudo / Utility Commands
   application.add_handler(CommandHandler("add", sudo_only_command_handler))

   # Event Handlers
   application.add_handler(ChatMemberHandler(log_joining_groups_handler, ChatMemberHandler.MY_CHAT_MEMBER))
   application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, check_guesses))
   application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, log_private_messages_handler))

   print("🚀 Lexicore Engine is ready.")
   application.run_polling()

if __name__ == "__main__":
   main()
