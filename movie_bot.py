
import logging
import os
import requests
import re
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# Dummy Web Server for Render
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Credentials (SECURE: Getting from Environment Variables)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "2735fa30231a3de0106b13ddd26c1226")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
WELCOME_IMAGE_URL = "https://files.manuscdn.com/user_upload_by_module/session_file/310519663694038442/kWSCOdymSBkwziok.png"

# Enhanced Mappings
GENRE_MAP_MOVIE = {
    "военный": 10752, "военные": 10752, "война": 10752,
    "боевик": 28, "боевики": 28, "комедия": 35, "комедии": 35,
    "ужасы": 27, "хоррор": 27, "драма": 18, "драмы": 18,
    "фантастика": 878, "фантастические": 878, "фэнтези": 14,
    "детектив": 9648, "детективы": 9648, "мелодрама": 10749,
    "триллер": 53, "мультфильм": 16, "приключения": 12
}

GENRE_MAP_TV = {
    "военный": 10768, "военные": 10768, "война": 10768,
    "боевик": 10759, "боевики": 10759,
    "комедия": 35, "комедии": 35, "драма": 18, "фантастика": 10765,
    "детектив": 9648, "криминал": 80, "документальный": 99
}

COUNTRY_MAP = {
    "американский": "US", "американские": "US", "сша": "US", "голливуд": "US",
    "русский": "RU", "русские": "RU", "россия": "RU",
    "корейский": "KR", "корейские": "KR", "дорама": "KR",
    "британский": "GB", "английский": "GB", "англия": "GB"
}

async def send_media_details(update: Update, item, media_type=None) -> None:
    m_type = media_type or item.get("media_type", "movie")
    title = item.get("title") if m_type == "movie" else item.get("name")
    original_title = item.get("original_title") if m_type == "movie" else item.get("original_name")
    release_date = item.get("release_date") if m_type == "movie" else item.get("first_air_date")
    overview = item.get("overview", "Описание отсутствует.")
    vote_average = item.get("vote_average", 0)
    poster_path = item.get("poster_path")

    icon = "🎬 Фильм" if m_type == "movie" else "📺 Сериал"
    year = release_date[:4] if release_date else "N/A"
    
    message_text = f"<b>{icon}:</b> {title} ({original_title})\n"
    message_text += f"<b>Год:</b> {year} | <b>Рейтинг:</b> {vote_average:.1f}/10\n"
    message_text += f"<b>Описание:</b> {overview[:350]}..." if len(overview) > 350 else f"<b>Описание:</b> {overview}"

    target = update.callback_query.message if update.callback_query else update.message
    if poster_path:
        await target.reply_photo(photo=f"{TMDB_IMAGE_BASE_URL}{poster_path}", caption=message_text, parse_mode="HTML")
    else:
        await target.reply_html(message_text)

async def start(update: Update, context) -> None:
    user = update.effective_user
    welcome_text = (
        f"Привет, {user.mention_html()}! 🎬\n\n"
        f"Я — <b>КиноГид от Swit</b>, твой персональный ассистент в мире кино.\n\n"
        f"<b>Что я умею:</b>\n"
        f"🔍 Найду любой фильм по названию\n"
        f"🔥 Покажу самые горячие /popular новинки\n"
        f"🎭 Подберу кино по /genres\n\n"
        f"Просто напиши название фильма или выбери команду ниже!"
    )
    try:
        await update.message.reply_photo(photo=WELCOME_IMAGE_URL, caption=welcome_text, parse_mode="HTML")
    except Exception:
        await update.message.reply_html(welcome_text)

async def popular_command(update: Update, context) -> None:
    await show_trending(update)

async def genres_command(update: Update, context) -> None:
    await get_genres(update, context)

async def handle_message(update: Update, context) -> None:
    query = update.message.text.lower().strip()
    
    if query in ["жанры", "жанр", "genres"]:
        await get_genres(update, context)
        return
    if query in ["популярное", "новинки", "popular"]:
        await show_trending(update)
        return

    words = re.findall(r'\w+', query)
    found_movie_genres = [GENRE_MAP_MOVIE[w] for w in words if w in GENRE_MAP_MOVIE]
    found_tv_genres = [GENRE_MAP_TV[w] for w in words if w in GENRE_MAP_TV]
    found_countries = [COUNTRY_MAP[w] for w in words if w in COUNTRY_MAP]
    
    year_match = re.search(r'\b(19|20)\d{2}\b', query)
    year = year_match.group(0) if year_match else None
    
    needs_tv = any(w in query for w in ["сериал", "сериалы", "tv", "show", "дорама"])
    needs_movie = any(w in query for w in ["фильм", "фильмы", "кино"])
    
    if not needs_tv and not needs_movie:
        needs_tv = True
        needs_movie = True

    final_results = []

    if found_movie_genres or found_countries or year:
        if needs_movie:
            params = {
                "api_key": TMDB_API_KEY, "language": "ru-RU", "sort_by": "popularity.desc",
                "with_genres": ",".join(map(str, found_movie_genres)) if found_movie_genres else None,
                "with_origin_country": "|".join(found_countries) if found_countries else None,
                "primary_release_year": year
            }
            res = requests.get(f"{TMDB_BASE_URL}/discover/movie", params=params).json()
            for item in res.get("results", [])[:3]:
                item["media_type"] = "movie"
                final_results.append(item)
        
        if needs_tv:
            params = {
                "api_key": TMDB_API_KEY, "language": "ru-RU", "sort_by": "popularity.desc",
                "with_genres": ",".join(map(str, found_tv_genres)) if found_tv_genres else None,
                "with_origin_country": "|".join(found_countries) if found_countries else None,
                "first_air_date_year": year
            }
            res = requests.get(f"{TMDB_BASE_URL}/discover/tv", params=params).json()
            for item in res.get("results", [])[:3]:
                item["media_type"] = "tv"
                final_results.append(item)

    if not final_results:
        params = {"api_key": TMDB_API_KEY, "query": query, "language": "ru-RU"}
        res = requests.get(f"{TMDB_BASE_URL}/search/multi", params=params).json()
        final_results = [i for i in res.get("results", []) if i.get("media_type") in ["movie", "tv"]][:5]

    if final_results:
        await update.message.reply_text(f"Вот лучшие находки по запросу '{query}':")
        final_results.sort(key=lambda x: x.get("popularity", 0), reverse=True)
        for item in final_results[:5]:
            await send_media_details(update, item)
    else:
        await update.message.reply_text("К сожалению, ничего не нашлось. Попробуйте упростить запрос.")

async def show_trending(update):
    res = requests.get(f"{TMDB_BASE_URL}/trending/all/day", params={"api_key": TMDB_API_KEY, "language": "ru-RU"}).json()
    if res.get("results"):
        await update.message.reply_text("Тренды дня:")
        for item in res.get("results")[:5]:
            await send_media_details(update, item)

async def get_genres(update, context):
    unique_genres = {}
    for name, gid in GENRE_MAP_MOVIE.items():
        if gid not in unique_genres: unique_genres[gid] = name
    keyboard = []
    genre_list = list(unique_genres.items())
    for i in range(0, len(genre_list), 2):
        row = [InlineKeyboardButton(genre_list[i][1].capitalize(), callback_data=f"g_{genre_list[i][0]}")]
        if i + 1 < len(genre_list):
            row.append(InlineKeyboardButton(genre_list[i+1][1].capitalize(), callback_data=f"g_{genre_list[i+1][0]}"))
        keyboard.append(row)
    await update.message.reply_text("Выберите жанр:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("g_"):
        gid = query.data.split("_")[1]
        params = {"api_key": TMDB_API_KEY, "with_genres": gid, "language": "ru-RU", "sort_by": "popularity.desc"}
        res = requests.get(f"{TMDB_BASE_URL}/discover/movie", params=params).json()
        if res.get("results"):
            await query.edit_message_text("Популярные фильмы в этом жанре:")
            for movie in res["results"][:3]:
                await send_media_details(update, movie, "movie")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("popular", popular_command))
    app.add_handler(CommandHandler("genres", genres_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
