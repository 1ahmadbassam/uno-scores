import os
import re
import asyncio
from datetime import datetime
from github import Github, GithubException, Auth
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GITHUB_REPO_NAME = os.getenv('GITHUB_REPO_NAME')
APP_ID = os.getenv('GITHUB_APP_ID')
try:
    INSTALLATION_ID = int(os.getenv('GITHUB_INSTALLATION_ID'))
except (ValueError, TypeError):
    INSTALLATION_ID = None
RAW_PRIVATE_KEY = os.getenv('RAW_PRIVATE_KEY')
AUTHORIZED_CHAT_ID = os.getenv('AUTHORIZED_CHAT_ID')
PLAYER_A_ID = os.getenv('PLAYER_A_ID')
PLAYER_I_ID = os.getenv('PLAYER_I_ID')
FILE_PATH = 'scores.csv'
BRANCH_NAME = 'master'

# --- GITHUB HELPER FUNCTIONS ---
def get_github_instance() -> Github:
    private_key = RAW_PRIVATE_KEY.replace('\\n', '\n')
    auth = Auth.AppAuth(APP_ID, private_key).get_installation_auth(INSTALLATION_ID)
    return Github(auth=auth)

def get_latest_score() -> tuple[int, int]:
    """Fetches and returns the last score from the CSV file."""
    g = get_github_instance()
    repo = g.get_repo(GITHUB_REPO_NAME)
    contents = repo.get_contents(FILE_PATH, ref=BRANCH_NAME)
    current_content = contents.decoded_content.decode('utf-8').strip()
    
    lines = current_content.split('\n')
    if len(lines) < 2:
        return 0, 0

    last_line = lines[-1]
    _, _, last_score_a, last_score_i = last_line.split(',')
    return int(last_score_a), int(last_score_i)

def update_csv_file(new_csv_line: str) -> tuple[bool, str | None]:
    try:
        g = get_github_instance()
        repo = g.get_repo(GITHUB_REPO_NAME)
        contents = repo.get_contents(FILE_PATH, ref=BRANCH_NAME)
        
        current_content = contents.decoded_content.decode('utf-8').strip()
        new_content = f"{current_content}\n{new_csv_line}"

        repo.update_file(
            path=contents.path,
            message=f"Update score: {new_csv_line.split(',')[2]}-{new_csv_line.split(',')[3]}",
            content=new_content,
            sha=contents.sha,
            branch=BRANCH_NAME
        )
        return True, None
    except GithubException as e:
        print(f"GitHub API Error: {e.status} - {e.data}")
        return False, f"GitHub API Error: {e.data.get('message', 'Unknown error')}"
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False, str(e)

# --- TELEGRAM COMMAND HANDLERS ---
async def set_score_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or str(update.message.chat_id) != AUTHORIZED_CHAT_ID:
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/setscore 142-91`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    score_text = context.args[0]
    if not re.match(r'^\d+-\d+$', score_text):
        await update.message.reply_text("Invalid format\\. Use `142-91`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    score_a, score_i = score_text.split('-')
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    new_csv_line = f"{date_str},{time_str},{score_a},{score_i}"

    processing_message = await update.message.reply_text("Updating score on GitHub...")
    success, error_message = await asyncio.to_thread(update_csv_file, new_csv_line)

    if success:
        safe_score_text = score_text.replace('-', '\\-')
        confirmation_text = f"✅ Score set to *{safe_score_text}*\\!"
        sent_message = await processing_message.edit_text(confirmation_text, parse_mode=ParseMode.MARKDOWN_V2)
        try:
            await context.bot.pin_chat_message(chat_id=update.message.chat_id, message_id=sent_message.message_id)
        except Exception as e:
            print(f"Could not pin message: {e}")
    else:
        error_text = f"❌ Failed to set score\\.\n*Error:* `{error_message}`"
        await processing_message.edit_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)

async def my_score_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or str(update.message.chat_id) != AUTHORIZED_CHAT_ID:
        return

    user_id = str(update.message.from_user.id)
    player = 'A' if user_id == PLAYER_A_ID else 'I' if user_id == PLAYER_I_ID else None
    if not player:
        await update.message.reply_text("You are not a registered player\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    processing_message = await update.message.reply_text(f"Fetching last score for Player {player}...")
    
    try:
        score_a, score_i = await asyncio.to_thread(get_latest_score)
        score_a += 1 if player == 'A' else 0
        score_i += 1 if player == 'I' else 0
            
        now = datetime.now()
        new_csv_line = f"{now.strftime('%Y-%m-%d')},{now.strftime('%H:%M')},{score_a},{score_i}"

        await processing_message.edit_text("Incrementing score on GitHub...")
        success, error_message = await asyncio.to_thread(update_csv_file, new_csv_line)

        if success:
            safe_score_text = f"{score_a}\\-{score_i}"
            confirmation_text = f"✅ Score is now *{safe_score_text}*\\!"
            sent_message = await processing_message.edit_text(confirmation_text, parse_mode=ParseMode.MARKDOWN_V2)
            try:
                await context.bot.pin_chat_message(chat_id=update.message.chat_id, message_id=sent_message.message_id)
            except Exception as e:
                print(f"Could not pin message: {e}")
        else:
            error_text = f"❌ Failed to increment score\\.\n*Error:* `{error_message}`"
            await processing_message.edit_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await processing_message.edit_text(f"An error occurred: `{e}`", parse_mode=ParseMode.MARKDOWN_V2)

async def score_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or str(update.message.chat_id) != AUTHORIZED_CHAT_ID:
        return
    
    try:
        score_a, score_i = await asyncio.to_thread(get_latest_score)
        total_score = score_a + score_i

        if total_score == 0:
            await update.message.reply_text("No scores recorded yet\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return

        # CORRECTED: Escape the '.' in the formatted strings
        ratio_str = f"{score_a / score_i:.2f}".replace('.', '\\.') + ":1" if score_i > 0 else "∞"
        percent_a = f"{(score_a / total_score) * 100:.1f}".replace('.', '\\.') + "%"
        percent_i = f"{(score_i / total_score) * 100:.1f}".replace('.', '\\.') + "%"

        stats_message = (
            f"📊 *Current Score Statistics*\n\n"
            f"🔹 *Score:* {score_a} \\- {score_i}\n"
            f"🔸 *Ratio \\(A/I\\):* {ratio_str}\n"
            f"📈 *Point Share:*\n"
            f"    \\- Player A: {percent_a}\n"
            f"    \\- Player I: {percent_i}"
        )
        await update.message.reply_text(stats_message, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        error_text = str(e).replace('.', '\\.')
        await update.message.reply_text(f"An error occurred while fetching stats: `{error_text}`", parse_mode=ParseMode.MARKDOWN_V2)

# --- MAIN BOT SETUP ---
def main() -> None:
    """Start the bot."""
    if not all([TELEGRAM_TOKEN, GITHUB_REPO_NAME, APP_ID, INSTALLATION_ID, RAW_PRIVATE_KEY, AUTHORIZED_CHAT_ID, PLAYER_A_ID, PLAYER_I_ID]):
        print("ERROR: Missing one or more environment variables.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("setscore", set_score_command))
    application.add_handler(CommandHandler("myscore", my_score_command))
    application.add_handler(CommandHandler("score", score_stats_command))

    print("Bot is running with GitHub App authentication...")
    application.run_polling()

if __name__ == '__main__':
    main()
