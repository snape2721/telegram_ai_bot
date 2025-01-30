import os
import logging
import datetime
import requests
import google.generativeai as genai
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from dotenv import load_dotenv
from google_search import search  # Import the search function

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Google Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-pro")  # Use the appropriate Gemini model

# MongoDB connection
client = MongoClient(MONGODB_URI)
db = client["telegram_bot"]

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📌 1️⃣ User Registration
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    username = user.username if user.username else "N/A"  # Handle missing usernames

    try:
        db.users.update_one(
            {"chat_id": user.id},
            {"$set": {"first_name": user.first_name, "username": username, "chat_id": user.id}},
            upsert=True
        )
        button = KeyboardButton("Share Contact", request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[button]], resize_keyboard=True)
        await update.message.reply_text("Welcome! Please share your contact.", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in user registration: {e}")
        await update.message.reply_text("Sorry, something went wrong during registration. Please try again later.")

# 📌 Handle Contact Sharing
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    try:
        db.users.update_one({"chat_id": update.message.chat_id}, {"$set": {"phone_number": contact.phone_number}})
        await update.message.reply_text("Thank you for sharing your contact!")
    except Exception as e:
        logger.error(f"Error in handling contact: {e}")
        await update.message.reply_text("Sorry, something went wrong while processing your contact. Please try again later.")

# 📌 2️⃣ Gemini-Powered Chatbot
async def gemini_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_message = update.message.text
    chat_id = user.id

    try:
        # Call Gemini API
        response = model.generate_content(user_message)
        bot_response = response.text if response.text else "Sorry, I couldn't process that."

        # Store chat history in MongoDB
        db.chat_history.insert_one({
            "chat_id": chat_id,
            "first_name": user.first_name,
            "username": user.username if user.username else "N/A",
            "user_message": user_message,
            "bot_response": bot_response,
            "timestamp": datetime.datetime.utcnow()
        })

        # Send response
        await update.message.reply_text(bot_response)

    except Exception as e:
        logger.error(f"Error in Gemini API: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again later.")

# 📌 Analyze File (Image)
async def analyze_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    file_id = update.message.document.file_id if update.message.document else update.message.photo[-1].file_id
    file = await context.bot.get_file(file_id)  # Get file URL
    file_path = file.file_path

    # Download file
    response = requests.get(file_path)
    file_name = f"downloads/{file_id}.jpg"  # Save file locally
    os.makedirs("downloads", exist_ok=True)
    with open(file_name, "wb") as f:
        f.write(response.content)

    try:
        image_response = model.generate_content(["Describe this image:", open(file_name, "rb")])
        analysis_text = image_response.text if image_response.text else "Couldn't analyze the image."

        # Saving metadata in MongoDB
        db.file_analysis.insert_one({
            "chat_id": user.id,
            "first_name": user.first_name,
            "username": user.username if user.username else "N/A",
            "file_name": file_name,
            "analysis": analysis_text,
            "timestamp": datetime.datetime.utcnow()
        })

        await update.message.reply_text(f"🖼 Image Analysis:\n{analysis_text}")

    except Exception as e:
        logger.error(f"Error in image analysis: {e}")
        await update.message.reply_text("Sorry, I couldn't analyze this image.")

# 📌 Web Search
async def web_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    query = " ".join(context.args)  

    if not query:
        await update.message.reply_text("Usage: /websearch <query>")
        return

    try:
        # Performing AI Web Search
        search_results = search(query) 
        summary = "\n".join([f"{i+1}. {result['title']} - {result['url']}" for i, result in enumerate(search_results)])

        # Storing search history in MongoDB
        db.web_search.insert_one({
            "chat_id": user.id,
            "first_name": user.first_name,
            "username": user.username if user.username else "N/A",
            "query": query,
            "results": summary,
            "timestamp": datetime.datetime.utcnow()
        })

        # Sending search results
        await update.message.reply_text(f"🔎 Web Search Results for: {query}\n\n{summary}")

    except Exception as e:
        logger.error(f"Error in web search: {e}")
        await update.message.reply_text("Sorry, I couldn't perform the search.")

if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Adding command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("websearch", web_search))  # Searching in web

    # Adding message handlers
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gemini_chat))  
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, analyze_file))  # Analysing image files

    application.run_polling()