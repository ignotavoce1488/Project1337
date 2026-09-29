"""Thin Telegram transport: validate, enqueue and serve owner-scoped documents."""

import asyncio
import re
import uuid
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from slovech.core.billing import format_hours, pack_price_rub, parse_pack_minutes
from slovech.core.billing_copy import BILLING_COPY
from slovech.core.config import SAFE_ID_REGEX, get_settings
from slovech.core.documents import render_docx
from slovech.core.languages import LANGUAGES, bot_copy, normalize_language
from slovech.core.legal import document_version, public_url
from slovech.core.storage import BillingRequired, ProcessingCancelled, QueueFull, Repository
from slovech.core.youtube import youtube_video_id

router = Router()

WELCOME_BANNER = Path(__file__).resolve().parents[2] / "web" / "assets" / "welcome.png"

# title, description, first step, second step, ready hint, consent hint,
# library button, language button, guide button, guide text
WELCOME_COPY = {
    "ru": ("Привет! Я Конспектъ 👋", "Превращаю записи в расшифровку и понятный конспект.",
           "Пришли аудио, голосовое или ссылку на YouTube.", "Я сообщу, когда всё будет готово.",
           "Конспекты, поиск и перевод — в твоей библиотеке.",
           "Сначала прими документы в сообщении ниже.", "Мои конспекты", "Язык", "Как это работает",
           "Пришли аудио, голосовое сообщение или ссылку на YouTube прямо в этот чат. "
           "Когда обработка закончится, я пришлю конспект и кнопку для открытия. "
           "В мини-приложении можно читать расшифровку, искать по записям, менять язык и скачать DOCX."),
    "en": ("Hi, I'm Konspekt 👋", "I turn recordings into transcripts and clear notes.",
           "Send audio, a voice message or a YouTube link.", "I'll let you know when it's ready.",
           "Your notes, search and translations live in your library.",
           "First, accept the documents in the message below.", "My notes", "Language", "How it works",
           "Send audio, a voice message or a YouTube link right here. I'll send you the notes when processing finishes. "
           "In the Mini App you can read the transcript, search recordings, change language and download DOCX."),
    "es": ("¡Hola! Soy Konspekt 👋", "Convierto grabaciones en transcripciones y notas claras.",
           "Envía audio, un mensaje de voz o un enlace de YouTube.", "Te avisaré cuando esté listo.",
           "Tus notas, búsquedas y traducciones están en tu biblioteca.",
           "Primero acepta los documentos del siguiente mensaje.", "Mis notas", "Idioma", "Cómo funciona",
           "Envía audio, un mensaje de voz o un enlace de YouTube aquí. Te enviaré las notas cuando estén listas. "
           "En la miniaplicación puedes leer la transcripción, buscar, cambiar el idioma y descargar DOCX."),
    "fr": ("Bonjour, je suis Konspekt 👋", "Je transforme les enregistrements en transcriptions et notes claires.",
           "Envoie un audio, un message vocal ou un lien YouTube.", "Je te préviendrai quand ce sera prêt.",
           "Tes notes, recherches et traductions sont dans ta bibliothèque.",
           "Accepte d'abord les documents dans le message ci-dessous.", "Mes notes", "Langue", "Mode d'emploi",
           "Envoie un audio, un message vocal ou un lien YouTube ici. Je t'enverrai les notes une fois prêtes. "
           "Dans la mini-app, tu peux lire la transcription, chercher, changer de langue et télécharger un DOCX."),
    "de": ("Hallo, ich bin Konspekt 👋", "Ich mache aus Aufnahmen Transkripte und klare Notizen.",
           "Sende Audio, eine Sprachnachricht oder einen YouTube-Link.", "Ich melde mich, wenn alles fertig ist.",
           "Notizen, Suche und Übersetzungen findest du in deiner Bibliothek.",
           "Bitte bestätige zuerst die Dokumente in der nächsten Nachricht.", "Meine Notizen", "Sprache", "So funktioniert's",
           "Sende Audio, eine Sprachnachricht oder einen YouTube-Link hierher. Ich schicke dir die Notizen, sobald sie fertig sind. "
           "In der Mini-App kannst du das Transkript lesen, suchen, die Sprache ändern und DOCX herunterladen."),
    "it": ("Ciao, sono Konspekt 👋", "Trasformo registrazioni in trascrizioni e appunti chiari.",
           "Invia un audio, un messaggio vocale o un link YouTube.", "Ti avviserò quando sarà pronto.",
           "Appunti, ricerca e traduzioni sono nella tua raccolta.",
           "Prima accetta i documenti nel messaggio qui sotto.", "I miei appunti", "Lingua", "Come funziona",
           "Invia qui un audio, un messaggio vocale o un link YouTube. Ti manderò gli appunti appena pronti. "
           "Nella mini app puoi leggere la trascrizione, cercare, cambiare lingua e scaricare il DOCX."),
    "pt": ("Olá, sou o Konspekt 👋", "Transformo gravações em transcrições e notas claras.",
           "Envie áudio, uma mensagem de voz ou um link do YouTube.", "Avisarei quando estiver pronto.",
           "Notas, busca e traduções ficam na sua biblioteca.",
           "Primeiro aceite os documentos na mensagem abaixo.", "Minhas notas", "Idioma", "Como funciona",
           "Envie áudio, uma mensagem de voz ou um link do YouTube aqui. Enviarei as notas quando estiverem prontas. "
           "No mini app você pode ler a transcrição, pesquisar, mudar o idioma e baixar DOCX."),
    "tr": ("Merhaba, ben Konspekt 👋", "Kayıtları transkripte ve anlaşılır notlara dönüştürüyorum.",
           "Ses dosyası, sesli mesaj veya YouTube bağlantısı gönder.", "Hazır olunca haber vereceğim.",
           "Notların, arama ve çeviriler kitaplığında.",
           "Önce aşağıdaki iletideki belgeleri kabul et.", "Notlarım", "Dil", "Nasıl çalışır",
           "Bu sohbete ses dosyası, sesli mesaj veya YouTube bağlantısı gönder. Hazır olunca notları yollayacağım. "
           "Mini uygulamada transkripti okuyabilir, arama yapabilir, dili değiştirebilir ve DOCX indirebilirsin."),
    "ar": ("مرحباً، أنا كونسبكت 👋", "أحوّل التسجيلات إلى تفريغ وملخص واضح.",
           "أرسل ملفاً صوتياً أو رسالة صوتية أو رابط يوتيوب.", "سأخبرك عندما يصبح جاهزاً.",
           "ملخصاتك والبحث والترجمات في مكتبتك.",
           "اقبل المستندات في الرسالة التالية أولاً.", "ملخصاتي", "اللغة", "كيف يعمل",
           "أرسل ملفاً صوتياً أو رسالة صوتية أو رابط يوتيوب في هذه المحادثة. سأرسل الملخص عند اكتماله. "
           "في التطبيق المصغر يمكنك قراءة التفريغ والبحث وتغيير اللغة وتنزيل DOCX."),
    "hi": ("नमस्ते, मैं Konspekt हूँ 👋", "रिकॉर्डिंग से ट्रांसक्रिप्ट और साफ़ नोट्स बनाता हूँ।",
           "ऑडियो, वॉइस मैसेज या YouTube लिंक भेजें।", "तैयार होने पर मैं बता दूँगा।",
           "नोट्स, खोज और अनुवाद आपकी लाइब्रेरी में हैं।",
           "पहले नीचे दिए संदेश में दस्तावेज़ स्वीकार करें।", "मेरे नोट्स", "भाषा", "कैसे काम करता है",
           "यहीं ऑडियो, वॉइस मैसेज या YouTube लिंक भेजें। तैयार होने पर मैं नोट्स भेजूँगा। "
           "मिनी ऐप में आप ट्रांसक्रिप्ट पढ़ सकते हैं, खोज सकते हैं, भाषा बदल सकते हैं और DOCX डाउनलोड कर सकते हैं।"),
    "tk": ("Salam, men Konspekt 👋", "Ýazgylardan transkript we düşnükli bellikler taýýarlaýaryn.",
           "Audio, ses habaryny ýa-da YouTube salgysyny iber.", "Taýýar bolanda habar bererin.",
           "Bellikler, gözleg we terjimeler kitaphanaňda.",
           "Ilki aşakdaky habardaky resminamalary kabul et.", "Belliklerim", "Dil", "Nähili işleýär",
           "Şu çata audio, ses habaryny ýa-da YouTube salgysyny iber. Taýýar bolanda bellikleri ibererin. "
           "Mini programmada transkripti okap, gözläp, dili üýtgedip we DOCX ýükläp alyp bolýar."),
}


def interface_language(repository: Repository, user) -> str:
    saved = repository.get_preferences(str(user.id))["interface_language"] if user else None
    return saved or normalize_language(getattr(user, "language_code", None), "ru")


async def ensure_interface_language(repository: Repository, user) -> str:
    code = interface_language(repository, user)
    if user and not repository.get_preferences(str(user.id))["interface_language"]:
        await asyncio.to_thread(repository.set_preferences, str(user.id), interface_language=code)
    return code


def language_keyboard() -> InlineKeyboardMarkup:
    rows = []
    buttons = [InlineKeyboardButton(text=name, callback_data=f"language:interface:{code}")
               for code, name in LANGUAGES.items()]
    for index in range(0, len(buttons), 2):
        rows.append(buttons[index:index + 2])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("language", "lang"))
async def choose_language(message: Message, repository: Repository):
    if message.chat.type != "private" or not message.from_user:
        return
    await message.answer("🌐 Interface language / Язык интерфейса", reply_markup=language_keyboard())


@router.callback_query(F.data.startswith("language:"))
async def save_language(query: CallbackQuery, repository: Repository):
    if not query.message or query.message.chat.type != "private" or query.message.chat.id != query.from_user.id:
        await query.answer("Open this in a private chat.", show_alert=True)
        return
    _, kind, code = ((query.data or "").split(":") + [""])[:3]
    if kind == "menu":
        await query.answer()
        await query.message.answer("🌐 Interface language / Язык интерфейса",
                                   reply_markup=language_keyboard())
        return
    if kind != "interface" or code not in LANGUAGES:
        await query.answer("Invalid language.", show_alert=True)
        return
    try:
        await asyncio.to_thread(repository.set_preferences, str(query.from_user.id),
                                interface_language=code)
    except ProcessingCancelled:
        await query.answer("Account is being deleted.", show_alert=True)
        return
    await query.answer("Saved")
    await query.message.edit_text(f"✅ {LANGUAGES[code]}")
    await send_welcome(query.message, repository.settings.domain, code, compact=True)


def is_admin(user) -> bool:
    if not user:
        return False
    if getattr(user, "username", "") and user.username.lower() == "inwhtmst":
        return True
    return bool(get_settings().admin_user_id > 0 and user.id == get_settings().admin_user_id)


@router.message(CommandStart())
async def handle_start(message: Message, repository: Repository):
    if message.chat.type != "private":
        return
    if message.from_user:
        stage = await asyncio.to_thread(repository.legal_stage, str(message.from_user.id))
        if stage == "deleting" or (repository.settings.legal_enforcement and stage != "ready"):
            if stage != "deleting":
                await send_welcome(message, repository.settings.domain,
                                   interface_language(repository, message.from_user), legal_pending=True)
            await send_legal_prompt(message, stage, repository.settings.domain)
            return
        await asyncio.to_thread(repository.touch, str(message.from_user.id))
    await send_welcome(message, repository.settings.domain,
                       await ensure_interface_language(repository, message.from_user))


@router.message(Command("revoke", "delete_me"))
async def handle_revoke(message: Message, repository: Repository):
    if message.from_user and message.chat.type == "private":
        if await asyncio.to_thread(repository.legal_stage, str(message.from_user.id)) == "deleting":
            await send_legal_prompt(message, "deleting", repository.settings.domain)
            return
        token = await asyncio.to_thread(repository.deletion_confirmation, str(message.from_user.id))
        await message.answer(
            "Удалить данные аккаунта? Будут остановлены задания и удалены "
            "все конспекты, расшифровки и история согласий, включая управляемые резервные копии. "
            "Отменить удаление после подтверждения нельзя.\n\n"
            "Для подтверждения уничтожения на 3 года останется минимальная запись: Telegram ID, "
            "дата, причина и перечень удалённых категорий, без содержимого записей.\n\n"
            "Сообщения в Telegram и копии у внешних поставщиков этой командой не удаляются.\n\n"
            "Кнопка подтверждения действует 10 минут.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Да, удалить мои данные", callback_data=f"erase:{token}"
                        ),
                        InlineKeyboardButton(text="Отмена", callback_data=f"erase_cancel:{token}"),
                    ]
                ]
            ),
        )


@router.callback_query(F.data.startswith("erase:") | F.data.startswith("erase_cancel:"))
async def handle_deletion_choice(query: CallbackQuery, bot: Bot, repository: Repository):
    if (
        not query.message
        or query.message.chat.type != "private"
        or query.message.chat.id != query.from_user.id
    ):
        await query.answer("Подтверждение доступно только в вашем личном чате.", show_alert=True)
        return
    action, token = (query.data or "").split(":", 1)
    user_id = str(query.from_user.id)
    if action == "erase_cancel":
        await asyncio.to_thread(repository.cancel_deletion_confirmation, user_id, token)
        await query.answer("Удаление отменено.")
        await query.message.edit_reply_markup(reply_markup=None)
        return
    confirmed = await asyncio.to_thread(repository.confirm_deletion, user_id, token)
    if not confirmed:
        await query.answer("Подтверждение устарело. Отправьте /delete_me заново.", show_alert=True)
        return
    await query.answer("Запрос принят.")
    await query.message.edit_reply_markup(reply_markup=None)
    await bot.send_message(
        query.from_user.id,
        "Доступ заблокирован, задания остановлены. Удаление данных запущено; "
        "сообщу о завершении отдельно.",
    )


@router.message(Command("privacy", "terms"))
async def handle_privacy(message: Message, repository: Repository):
    if not repository.settings.legal_enforcement:
        await message.answer("Документы пока не опубликованы.")
        return
    await message.answer(
        f"Соглашение: {public_url(repository.settings.domain, 'terms')}\n"
        f"Политика: {public_url(repository.settings.domain, 'privacy')}\n"
        f"Согласие: {public_url(repository.settings.domain, 'consent')}\n\n"
        "Удаление данных: /delete_me (с подтверждением)."
    )


async def send_welcome(message: Message, domain: str, language: str = "ru", *,
                       legal_pending: bool = False, compact: bool = False):
    title, description, first, second, ready_hint, consent_hint, library, lang, guide, _ = (
        WELCOME_COPY.get(language, WELCOME_COPY["en"])
    )
    caption = (f"<b>{title}</b>\n{description}\n\n"
               f"① {first}\n② {second}\n\n"
               f"<i>{consent_hint if legal_pending else ready_hint}</i>")
    keyboard = None if legal_pending else InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📚 {library}", web_app=WebAppInfo(url=f"{domain}/app?v=13"))],
        [InlineKeyboardButton(text=f"🌐 {lang}", callback_data="language:menu:interface"),
         InlineKeyboardButton(text=f"❔ {guide}", callback_data="welcome:guide")],
        [InlineKeyboardButton(text=f"💳 {BILLING_COPY.get(language, BILLING_COPY['en'])[0]}",
                              callback_data="billing:plans")],
    ])
    if compact:
        await message.answer(f"✅ {ready_hint}", reply_markup=keyboard)
        return
    await message.answer_photo(
        FSInputFile(WELCOME_BANNER), caption=caption, parse_mode="HTML", reply_markup=keyboard,
    )


@router.callback_query(F.data == "welcome:guide")
async def show_welcome_guide(query: CallbackQuery, repository: Repository):
    if not query.message or query.message.chat.type != "private" or query.message.chat.id != query.from_user.id:
        await query.answer("Open this in a private chat.", show_alert=True)
        return
    language = interface_language(repository, query.from_user)
    await query.answer()
    await query.message.answer("🎙 " + WELCOME_COPY.get(language, WELCOME_COPY["en"])[-1])


def billing_keyboard(language: str) -> InlineKeyboardMarkup:
    copy = BILLING_COPY.get(language, BILLING_COPY["en"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⏱ {copy[5]}", callback_data="billing:hours")],
        [InlineKeyboardButton(text=f"💠 {copy[6]}", callback_data="billing:subscription")],
    ])


async def send_plans(message: Message, repository: Repository, user):
    locale = interface_language(repository, user)
    copy = BILLING_COPY.get(locale, BILLING_COPY["en"])
    body = f"💳 <b>{copy[0]}</b>\n\n• {copy[1]}\n• {copy[2]}\n• {copy[3]}\n\n{copy[4]}"
    status = await asyncio.to_thread(repository.billing_status, str(user.id))
    if status["unlimited"]:
        body += "\n\n♾ Безлимит активен для этого аккаунта." if locale == "ru" else (
            "\n\n♾ Unlimited access is active for this account."
        )
    elif repository.settings.billing_enforcement:
        body += f"\n\n{copy[11].format(count=status['free_remaining'])}"
    await message.answer(body, parse_mode="HTML",
                         reply_markup=None if status["unlimited"] else billing_keyboard(locale))


@router.message(Command("myid"))
async def show_telegram_id(message: Message):
    if message.chat.type == "private" and message.from_user:
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")


@router.message(Command("plans", "tariffs"))
async def show_plans_command(message: Message, repository: Repository):
    if message.chat.type == "private" and message.from_user:
        await send_plans(message, repository, message.from_user)


@router.callback_query(F.data.startswith("billing:"))
async def handle_billing_menu(query: CallbackQuery, repository: Repository):
    if not query.message or query.message.chat.type != "private" or query.message.chat.id != query.from_user.id:
        await query.answer("Open this in a private chat.", show_alert=True)
        return
    action = (query.data or "").split(":", 1)[-1]
    copy = BILLING_COPY.get(interface_language(repository, query.from_user), BILLING_COPY["en"])
    if action == "plans":
        await query.answer()
        await send_plans(query.message, repository, query.from_user)
    elif action == "hours":
        try:
            await asyncio.to_thread(repository.expect_pack_amount, str(query.from_user.id))
        except ProcessingCancelled:
            await query.answer("Account is being deleted.", show_alert=True)
            return
        await query.answer()
        await query.message.answer(copy[7])
    elif action == "subscription":
        await query.answer()
        await query.message.answer(copy[10])
    else:
        await query.answer("Unknown option.", show_alert=True)


async def send_legal_prompt(message: Message, stage: str, domain: str):
    if stage == "deleting":
        await message.answer(
            "Данные аккаунта удаляются. До завершения новые записи недоступны. "
            "Если подтверждение не придёт в течение суток, повторите /start."
        )
        return
    if stage == "terms":
        title = "Перед началом прочитайте пользовательское соглашение и политику обработки данных."
        links = [
            [
                InlineKeyboardButton(text="Соглашение", url=public_url(domain, "terms")),
                InlineKeyboardButton(text="Политика", url=public_url(domain, "privacy")),
            ]
        ]
        accept = "Принимаю соглашение"
    else:
        title = "Отдельно ознакомьтесь с согласием на обработку персональных данных."
        links = [
            [InlineKeyboardButton(text="Прочитать согласие", url=public_url(domain, "consent"))]
        ]
        accept = "Даю согласие"
    links.append(
        [
            InlineKeyboardButton(
                text=accept,
                callback_data=f"legal:{stage}:yes:{document_version(stage)[:16]}",
            ),
            InlineKeyboardButton(
                text="Не согласен",
                callback_data=f"legal:{stage}:no:{document_version(stage)[:16]}",
            ),
        ]
    )
    await message.answer(
        f"{title}\n\nБез принятия документов бот не принимает записи. Отказ не удаляет историю: для отзыва и удаления используйте /revoke.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=links),
    )


@router.callback_query(F.data.startswith("legal:"))
async def handle_legal_choice(query: CallbackQuery, bot: Bot, repository: Repository):
    parts = (query.data or "").split(":")
    if len(parts) != 4 or parts[1] not in {"terms", "consent"} or parts[2] not in {"yes", "no"}:
        await query.answer("Недопустимый выбор.", show_alert=True)
        return
    user_id = str(query.from_user.id)
    if (
        not query.message
        or query.message.chat.type != "private"
        or query.message.chat.id != query.from_user.id
    ):
        await query.answer("Откройте условия в личном чате через /start.", show_alert=True)
        return
    if not repository.settings.legal_enforcement:
        await query.answer("Условия сейчас обновляются. Введите /start.", show_alert=True)
        return
    if parts[3] != document_version(parts[1])[:16]:
        await query.answer(
            "Документы обновились. Введите /start и ознакомьтесь с ними снова.", show_alert=True
        )
        return
    if parts[2] == "no":
        await query.answer("Вы отказались.")
        await bot.send_message(
            query.from_user.id,
            "Новая редакция не принята, обработка по ней не начнётся. Чтобы отозвать ранее данное согласие и удалить историю, отправьте /revoke. Чтобы прочитать условия снова — /start.",
        )
        return
    stage = await asyncio.to_thread(repository.legal_stage, user_id)
    if stage != parts[1]:
        await query.answer("Откройте актуальные условия через /start.", show_alert=True)
        return
    try:
        await asyncio.to_thread(repository.accept_legal, user_id, stage, parts[3])
    except (ProcessingCancelled, ValueError):
        await query.answer("Состояние изменилось. Отправьте /start.", show_alert=True)
        return
    await query.answer("Сохранено.")
    if stage == "terms":
        await send_legal_prompt(query.message, "consent", repository.settings.domain)
    else:
        await send_welcome(query.message, repository.settings.domain,
                           await ensure_interface_language(repository, query.from_user), compact=True)


@router.message(Command("admin"))
async def handle_admin(message: Message, repository: Repository):
    if not is_admin(message.from_user):
        return

    def stats():
        with repository.connection() as db:
            jobs = dict(db.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state").fetchall())
            total_lectures = db.execute("SELECT COUNT(*) FROM lectures").fetchone()[0]
            unique_users = db.execute("SELECT COUNT(DISTINCT user_id) FROM lectures").fetchone()[0]
            return jobs, total_lectures, unique_users

    jobs, total_lectures, unique_users = await asyncio.to_thread(stats)
    await message.answer(
        f"📊 <b>Статистика системы</b>\n\n"
        f"👥 Пользователей: {unique_users}\n"
        f"📚 Конспектов: {total_lectures}\n\n"
        f"⚙️ <b>Очередь задач</b>\n"
        f"В очереди: {jobs.get('pending', 0)}\n"
        f"В работе: {jobs.get('running', 0)}\n"
        f"Завершено: {jobs.get('done', 0)}\n"
        f"Ошибок: {jobs.get('failed', 0)}",
        parse_mode="HTML",
    )


async def enqueue(message: Message, repository: Repository, payload: dict):
    if not message.from_user or message.chat.type != "private":
        await message.answer("Обработка доступна в личном чате с ботом.")
        return
    stage = await asyncio.to_thread(repository.legal_stage, str(message.from_user.id))
    if stage == "deleting" or (repository.settings.legal_enforcement and stage != "ready"):
        await send_legal_prompt(message, stage, repository.settings.domain)
        return
    locale = interface_language(repository, message.from_user)
    status = await message.answer("⏳ " + bot_copy(locale, 0))
    payload.update(chat_id=message.chat.id, status_id=status.message_id)
    payload["output_language"] = locale
    try:
        created = await asyncio.to_thread(
            repository.enqueue,
            uuid.uuid4().hex,
            f"{message.chat.id}:{message.message_id}",
            str(message.from_user.id),
            payload,
        )
    except QueueFull:
        await status.edit_text(
            bot_copy(locale, 3)
        )
        return
    except BillingRequired:
        await status.edit_text("Бесплатные разборы закончились. Проверьте тарифы через /plans.")
        return
    except ProcessingCancelled:
        await status.edit_text("Данные аккаунта удаляются. Запись не принята.")
        return
    await status.edit_text(
        "⏳ " + bot_copy(locale, 1)
        if created
        else bot_copy(locale, 2)
    )


@router.message(F.audio | F.voice | F.document)
async def handle_audio(message: Message, repository: Repository):
    media = message.voice or message.audio or message.document
    if not media:
        return
    if (
        message.document
        and not (media.mime_type or "").startswith("audio/")
        and not (media.file_name or "")
        .lower()
        .endswith((".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac"))
    ):
        await message.answer("Поддерживаются только аудиофайлы.")
        return
    if not media.file_size or media.file_size > get_settings().max_upload_bytes:
        await message.answer(
            f"Размер файла должен быть не более {get_settings().max_upload_bytes // (1024 * 1024)} МБ."
        )
        return
    await enqueue(
        message,
        repository,
        {"kind": "audio", "file_id": media.file_id, "file_name": getattr(media, "file_name", None)},
    )


@router.message(F.text)
async def handle_youtube_link(message: Message, repository: Repository):
    if message.chat.type == "private" and message.from_user and (
        await asyncio.to_thread(repository.awaiting_pack_amount, str(message.from_user.id))
    ) and not re.search(r"https?://\S+", message.text or ""):
        copy = BILLING_COPY.get(interface_language(repository, message.from_user), BILLING_COPY["en"])
        try:
            minutes = parse_pack_minutes(message.text or "")
        except ValueError:
            await message.answer(copy[8])
            return
        await asyncio.to_thread(repository.clear_pack_amount_prompt, str(message.from_user.id))
        await message.answer(copy[9].format(hours=format_hours(minutes), price=pack_price_rub(minutes)))
        return
    match = re.search(r"https?://\S+", message.text or "")
    try:
        video = youtube_video_id(match.group(0) if match else "")
    except ValueError:
        await message.answer("Отправьте аудио, голосовое сообщение или ссылку на видео YouTube.")
        return
    await enqueue(
        message,
        repository,
        {"kind": "youtube", "url": f"https://www.youtube.com/watch?v={video}", "video_id": video},
    )


@router.callback_query(F.data.startswith("dl_"))
async def handle_download_docx(query: CallbackQuery, bot: Bot, repository: Repository):
    stage = await asyncio.to_thread(repository.legal_stage, str(query.from_user.id))
    if stage == "deleting" or (repository.settings.legal_enforcement and stage != "ready"):
        await query.answer("Доступ недоступен. Проверьте состояние через /start.", show_alert=True)
        return
    parts = (query.data or "")[3:].split("_", 1)
    lang, lecture_id = (
        (parts[0], parts[1])
        if len(parts) == 2 and parts[0] in {*LANGUAGES, "orig"}
        else ("ru", (query.data or "")[3:])
    )
    lecture = (
        await asyncio.to_thread(repository.get, lecture_id, str(query.from_user.id))
        if SAFE_ID_REGEX.fullmatch(lecture_id)
        else None
    )
    if not lecture:
        await query.answer("Запись не найдена.", show_alert=True)
        return
    await query.answer("Готовлю документ…")
    body, name = await asyncio.to_thread(render_docx, lecture, lang)
    await bot.send_document(query.from_user.id, BufferedInputFile(body, filename=name))
