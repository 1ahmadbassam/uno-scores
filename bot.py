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

# --- GITHUB AUTHENTICATION & FILE UPDATE LOGIC ---
def get_github_instance() -> Github:
    private_key = RAW_PRIVATE_KEY.replace('\\n', '\n')
    auth = Auth.AppAuth(APP_ID, private_key).get_installation_auth(INSTALLATION_ID)
    return Github(auth=auth)

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
async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or str(update.message.chat_id) != AUTHORIZED_CHAT_ID:
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/score 142-91`", parse_mode=ParseMode.MARKDOWN_V2)
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
    player = None
    if user_id == PLAYER_A_ID:
        player = 'A'
    elif user_id == PLAYER_I_ID:
        player = 'I'
    else:
        await update.message.reply_text("You are not a registered player\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    processing_message = await update.message.reply_text(f"Fetching last score for Player {player}...")
    
    try:
        g = get_github_instance()
        repo = g.get_repo(GITHUB_REPO_NAME)
        contents = repo.get_contents(FILE_PATH, ref=BRANCH_NAME)
        current_content = contents.decoded_content.decode('utf-8').strip()
        
        last_line = current_content.split('\n')[-1]
        _, _, last_score_a, last_score_i = last_line.split(',')
        
        score_a, score_i = int(last_score_a), int(last_score_i)

        if player == 'A':
            score_a += 1
        else: # Player I
            score_i += 1
            
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M')
        new_csv_line = f"{date_str},{time_str},{score_a},{score_i}"

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


# --- MAIN BOT SETUP ---
def main() -> None:
    """Start the bot."""
    if not all([TELEGRAM_TOKEN, GITHUB_REPO_NAME, APP_ID, INSTALLATION_ID, RAW_PRIVATE_KEY, AUTHORIZED_CHAT_ID, PLAYER_A_ID, PLAYER_I_ID]):
        print("ERROR: Missing one or more environment variables. Please set all required variables.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("score", score_command))
    application.add_handler(CommandHandler("myscore", my_score_command))

    print("@UnoScoresBot running...")
    application.run_polling()

if __name__ == '__main__':
    main()
