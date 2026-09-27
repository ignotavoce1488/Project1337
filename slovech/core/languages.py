"""User interface and speech language choices."""

LANGUAGES = {
    "ru": "Русский", "en": "English", "es": "Español", "fr": "Français",
    "de": "Deutsch", "it": "Italiano", "pt": "Português", "tr": "Türkçe",
    "ar": "العربية", "hi": "हिन्दी", "tk": "Türkmençe",
}

# Routine bot messages. Legal notices are maintained separately from product copy.
BOT_COPY = {
    "ru": ["Запись добавляется в очередь…", "Запись в очереди. Сообщу, когда конспект будет готов.", "Эта запись уже принята в обработку.", "Очередь заполнена. Повторите позже.", "Конспект готов.", "Открыть конспект", "Скачать DOCX", "Конспект готов — отправлен отдельным сообщением."],
    "en": ["Adding your recording to the queue…", "Your recording is queued. I'll let you know when the notes are ready.", "This recording is already being processed.", "The queue is full. Please try again later.", "Your notes are ready.", "Open notes", "Download DOCX", "Notes sent in a separate message."],
    "es": ["Añadiendo la grabación a la cola…", "La grabación está en cola. Te avisaré cuando estén listas las notas.", "Esta grabación ya se está procesando.", "La cola está llena. Inténtalo más tarde.", "Las notas están listas.", "Abrir notas", "Descargar DOCX", "Las notas se enviaron en otro mensaje."],
    "fr": ["Ajout de l’enregistrement à la file…", "L’enregistrement est en attente. Je vous préviendrai lorsque les notes seront prêtes.", "Cet enregistrement est déjà en cours de traitement.", "La file est pleine. Réessayez plus tard.", "Vos notes sont prêtes.", "Ouvrir les notes", "Télécharger DOCX", "Notes envoyées dans un autre message."],
    "de": ["Aufnahme wird zur Warteschlange hinzugefügt…", "Die Aufnahme wartet. Ich melde mich, sobald die Notizen fertig sind.", "Diese Aufnahme wird bereits verarbeitet.", "Die Warteschlange ist voll. Bitte später erneut versuchen.", "Deine Notizen sind fertig.", "Notizen öffnen", "DOCX herunterladen", "Notizen wurden separat gesendet."],
    "it": ["Aggiungo la registrazione alla coda…", "La registrazione è in coda. Ti avviserò quando gli appunti saranno pronti.", "Questa registrazione è già in elaborazione.", "La coda è piena. Riprova più tardi.", "Gli appunti sono pronti.", "Apri appunti", "Scarica DOCX", "Appunti inviati in un messaggio separato."],
    "pt": ["Adicionando gravação à fila…", "A gravação está na fila. Avisarei quando as notas estiverem prontas.", "Esta gravação já está em processamento.", "A fila está cheia. Tente novamente mais tarde.", "Suas notas estão prontas.", "Abrir notas", "Baixar DOCX", "Notas enviadas em outra mensagem."],
    "tr": ["Kayıt sıraya ekleniyor…", "Kayıt sırada. Notlar hazır olunca haber vereceğim.", "Bu kayıt zaten işleniyor.", "Sıra dolu. Lütfen daha sonra tekrar deneyin.", "Notlarınız hazır.", "Notları aç", "DOCX indir", "Notlar ayrı bir mesajda gönderildi."],
    "ar": ["جارٍ إضافة التسجيل إلى قائمة الانتظار…", "التسجيل في قائمة الانتظار. سأخبرك عند تجهيز الملخص.", "هذا التسجيل قيد المعالجة بالفعل.", "قائمة الانتظار ممتلئة. حاول لاحقاً.", "الملخص جاهز.", "افتح الملخص", "تنزيل DOCX", "أُرسل الملخص في رسالة منفصلة."],
    "hi": ["रिकॉर्डिंग कतार में जोड़ी जा रही है…", "रिकॉर्डिंग कतार में है। नोट्स तैयार होने पर बताऊँगा।", "यह रिकॉर्डिंग पहले से संसाधित हो रही है।", "कतार भरी है। बाद में फिर कोशिश करें।", "नोट्स तैयार हैं।", "नोट्स खोलें", "DOCX डाउनलोड करें", "नोट्स अलग संदेश में भेज दिए गए हैं।"],
    "tk": ["Ýazgy nobata goşulýar…", "Ýazgy nobatda. Bellikler taýýar bolanda habar bererin.", "Bu ýazgy eýýäm işlenýär.", "Nobat doly. Soňrak gaýtadan synanyşyň.", "Bellikler taýýar.", "Bellikleri aç", "DOCX ýükläp al", "Bellikler aýratyn habar bilen iberildi."],
}


def bot_copy(code: str, index: int) -> str:
    return BOT_COPY.get(code, BOT_COPY["en"])[index]


def normalize_language(value: str | None, default: str = "en") -> str:
    code = (value or "").lower().replace("_", "-").split("-", 1)[0]
    return code if code in LANGUAGES else default
