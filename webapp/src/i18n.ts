// Mini App UI texts in the learner's base language (ru / uz / en). The admin dashboard stays in Russian.
// Before /api/me answers, Telegram's own language is used; then the base language chosen in the bot.

export type Locale = "ru" | "uz" | "en";

const ru = {
  "app.openFromBot": "Открой приложение из Telegram-бота @rimy_ai_bot",
  "app.loading": "Загружаю Rimy…",
  "tab.add": "Добавить", "tab.review": "Повторить", "tab.words": "Слова", "tab.profile": "Профиль", "tab.admin": "Дашборд",

  "add.eyebrow": "Новое слово",
  "add.title": "Скажи слово,\nкарточка готова",
  "add.sub": "Хоть по-русски: {mascot} переведёт, найдёт пример и озвучит",
  "add.tap": "Нажми и скажи слово",
  "add.listening": "Слушаю… нажми, когда закончишь",
  "add.micStart": "Сказать слово голосом", "add.micStop": "Остановить запись",
  "add.or": "или напиши",
  "add.placeholder": "Слово ({lang} или русский)",
  "add.analyze": "Разобрать слово",
  "add.thinking": "{mascot} листает словарик",
  "add.voiceLeft": "Голосовых на сегодня: {n}",
  "add.saved": "«{word}» в колоде! Повторим во вкладке «Повторить».",
  "add.heard": "Расслышал:",
  "add.didYouMean": "Может, имелось в виду:",
  "add.notFound": "Не нашёл такого слова. Проверь написание.",
  "add.pickMany": "Выбери значения", "add.pickOne": "Значение",
  "add.duplicate": "Уже есть в колоде: {t}",
  "add.save": "Сохранить в колоду",

  "rev.loading": "Достаю карточки…",
  "rev.doneCount": "Повторено: {n}. Ты супер!",
  "rev.allDone": "На сейчас всё повторено",
  "rev.nextIn": "Следующая карточка через {t}",
  "rev.addFirst": "Добавь первые слова во вкладке «Добавить»",
  "rev.eyebrow": "Повторение", "rev.left": "осталось {n}",
  "rev.answer": "Твой ответ", "rev.check": "Проверить",
  "rev.voice": "Голосом", "rev.stop": "Стоп", "rev.show": "Показать", "rev.checking": "Проверяю",
  "rev.correct": "Верно!", "rev.almost": "Почти!", "rev.wrong": "Не совсем",
  "rev.yourAnswer": "Твой ответ:", "rev.howEasy": "Как легко вспомнилось?",
  "rev.again": "Снова", "rev.hard": "Трудно", "rev.good": "Хорошо", "rev.easy": "Легко",
  "speak": "Озвучить", "delete": "Удалить",

  "words.loading": "Загружаю слова…", "words.title": "Мои слова",
  "words.search": "Поиск по словам и переводам", "words.none": "Ничего не нашлось",
  "words.empty": "Пока пусто. Добавь первое слово голосом!", "words.confirmDelete": "Удалить «{word}»?",

  "prof.hello": "Привет!", "prof.premiumUntil": "Premium до {d}", "prof.free": "Бесплатный тариф",
  "prof.words": "слов", "prof.due": "к повторению", "prof.today": "повторено сегодня", "prof.streak": "дней подряд",
  "prof.premiumActive": "Premium активен", "prof.premiumThanks": "Без лимитов до {d}. Спасибо, что ты с нами!",
  "prof.todayFree": "Сегодня на бесплатном тарифе", "prof.goPremium": "Premium без лимитов",
  "prof.promoWaiting": "Промокод ждёт оплаты: +{n} дн. начислятся вместе с Premium",
  "prof.learning": "Учу язык", "prof.base": "Язык общения", "prof.baseHint": "Переводы, объяснения и ответы {mascot}",
  "quota.word": "AI-слова", "quota.voice": "Голосовые", "quota.chat": "Сообщения маскоту", "quota.check": "AI-проверки ответов",

  "promo.title": "Промокод", "promo.hint": "Код от команды Rimy добавит дни к Premium", "promo.apply": "Применить",

  "pay.perk1": "Без лимита на AI-слова и голосовые", "pay.perk2": "Безлимитная AI-проверка ответов",
  "pay.perk3": "Разговорная практика с {mascot}", "pay.perk4": "Все языки сразу",
  "pay.promoAdds": "Твой промокод добавит ещё +{n} дн.", "pay.subscribe": "Подписаться за {n} Stars в месяц",
  "pay.havePromo": "У меня есть промокод", "pay.notNow": "Не сейчас", "pay.reviewFree": "Повторение карточек всегда бесплатно",
};

type Key = keyof typeof ru;

const uz: Record<Key, string> = {
  "app.openFromBot": "Ilovani @rimy_ai_bot Telegram botidan och",
  "app.loading": "Rimy yuklanmoqda…",
  "tab.add": "Qo'shish", "tab.review": "Takrorlash", "tab.words": "So'zlar", "tab.profile": "Profil", "tab.admin": "Dashbord",

  "add.eyebrow": "Yangi so'z",
  "add.title": "So'zni ayt,\nkarta tayyor",
  "add.sub": "O'zbekcha aytsang ham bo'ladi: {mascot} tarjima qiladi, misol topadi va o'qib beradi",
  "add.tap": "Bos va so'zni ayt",
  "add.listening": "Tinglayapman… tugatgach bos",
  "add.micStart": "So'zni ovoz bilan aytish", "add.micStop": "Yozishni to'xtatish",
  "add.or": "yoki yoz",
  "add.placeholder": "So'z ({lang} yoki o'zbekcha)",
  "add.analyze": "So'zni tahlil qilish",
  "add.thinking": "{mascot} lug'atni varaqlayapti",
  "add.voiceLeft": "Bugun qolgan ovozli so'zlar: {n}",
  "add.saved": "«{word}» to'plamga qo'shildi! «Takrorlash» bo'limida takrorlaymiz.",
  "add.heard": "Eshitdim:",
  "add.didYouMean": "Balki buni nazarda tutgandirsan:",
  "add.notFound": "Bunday so'z topilmadi. Yozilishini tekshir.",
  "add.pickMany": "Ma'nolarni tanla", "add.pickOne": "Ma'nosi",
  "add.duplicate": "To'plamda allaqachon bor: {t}",
  "add.save": "To'plamga saqlash",

  "rev.loading": "Kartalarni olayapman…",
  "rev.doneCount": "Takrorlandi: {n}. Zo'r!",
  "rev.allDone": "Hozircha hammasi takrorlandi",
  "rev.nextIn": "Keyingi karta {t} dan keyin",
  "rev.addFirst": "Birinchi so'zlarni «Qo'shish» bo'limida qo'sh",
  "rev.eyebrow": "Takrorlash", "rev.left": "qoldi: {n}",
  "rev.answer": "Javobing", "rev.check": "Tekshirish",
  "rev.voice": "Ovoz bilan", "rev.stop": "To'xtat", "rev.show": "Ko'rsatish", "rev.checking": "Tekshiryapman",
  "rev.correct": "To'g'ri!", "rev.almost": "Deyarli!", "rev.wrong": "Unchalik emas",
  "rev.yourAnswer": "Javobing:", "rev.howEasy": "Qanchalik oson esingga tushdi?",
  "rev.again": "Qayta", "rev.hard": "Qiyin", "rev.good": "Yaxshi", "rev.easy": "Oson",
  "speak": "Tinglash", "delete": "O'chirish",

  "words.loading": "So'zlar yuklanmoqda…", "words.title": "Mening so'zlarim",
  "words.search": "So'z va tarjimalar bo'yicha qidirish", "words.none": "Hech narsa topilmadi",
  "words.empty": "Hozircha bo'sh. Birinchi so'zni ovoz bilan qo'sh!", "words.confirmDelete": "«{word}» o'chirilsinmi?",

  "prof.hello": "Salom!", "prof.premiumUntil": "Premium {d} gacha", "prof.free": "Bepul tarif",
  "prof.words": "so'z", "prof.due": "takrorlash kerak", "prof.today": "bugun takrorlandi", "prof.streak": "kun ketma-ket",
  "prof.premiumActive": "Premium faol", "prof.premiumThanks": "{d} gacha cheklovsiz. Biz bilan ekaning uchun rahmat!",
  "prof.todayFree": "Bugun bepul tarifda", "prof.goPremium": "Cheklovsiz Premium",
  "prof.promoWaiting": "Promokod to'lovni kutmoqda: Premium bilan birga +{n} kun qo'shiladi",
  "prof.learning": "O'rganayotgan tilim", "prof.base": "Muloqot tili", "prof.baseHint": "Tarjimalar, izohlar va {mascot} javoblari",
  "quota.word": "AI so'zlar", "quota.voice": "Ovozli xabarlar", "quota.chat": "Rimy bilan suhbat", "quota.check": "AI javob tekshiruvi",

  "promo.title": "Promokod", "promo.hint": "Rimy jamoasidan kod Premium'ga kun qo'shadi", "promo.apply": "Qo'llash",

  "pay.perk1": "AI so'zlar va ovozli xabarlar cheklovsiz", "pay.perk2": "Cheklovsiz AI javob tekshiruvi",
  "pay.perk3": "{mascot} bilan suhbat amaliyoti", "pay.perk4": "Barcha tillar birdaniga",
  "pay.promoAdds": "Promokoding yana +{n} kun qo'shadi", "pay.subscribe": "Oyiga {n} Stars evaziga obuna bo'lish",
  "pay.havePromo": "Menda promokod bor", "pay.notNow": "Hozir emas", "pay.reviewFree": "Kartalarni takrorlash doim bepul",
};

const en: Record<Key, string> = {
  "app.openFromBot": "Open the app from the Telegram bot @rimy_ai_bot",
  "app.loading": "Loading Rimy…",
  "tab.add": "Add", "tab.review": "Review", "tab.words": "Words", "tab.profile": "Profile", "tab.admin": "Dashboard",

  "add.eyebrow": "New word",
  "add.title": "Say a word,\nget a card",
  "add.sub": "Even in English: {mascot} translates it, finds an example and says it aloud",
  "add.tap": "Tap and say a word",
  "add.listening": "Listening… tap when you're done",
  "add.micStart": "Say a word", "add.micStop": "Stop recording",
  "add.or": "or type it",
  "add.placeholder": "A word ({lang} or English)",
  "add.analyze": "Look up the word",
  "add.thinking": "{mascot} is checking the dictionary",
  "add.voiceLeft": "Voice words left today: {n}",
  "add.saved": "“{word}” is in your deck! Review it in the Review tab.",
  "add.heard": "Heard:",
  "add.didYouMean": "Did you mean:",
  "add.notFound": "Couldn't find that word. Check the spelling.",
  "add.pickMany": "Pick the meanings", "add.pickOne": "Meaning",
  "add.duplicate": "Already in your deck: {t}",
  "add.save": "Save to deck",

  "rev.loading": "Getting your cards…",
  "rev.doneCount": "Reviewed: {n}. Great job!",
  "rev.allDone": "All caught up for now",
  "rev.nextIn": "Next card in {t}",
  "rev.addFirst": "Add your first words in the Add tab",
  "rev.eyebrow": "Review", "rev.left": "{n} left",
  "rev.answer": "Your answer", "rev.check": "Check",
  "rev.voice": "By voice", "rev.stop": "Stop", "rev.show": "Show", "rev.checking": "Checking",
  "rev.correct": "Correct!", "rev.almost": "Almost!", "rev.wrong": "Not quite",
  "rev.yourAnswer": "Your answer:", "rev.howEasy": "How easy was it?",
  "rev.again": "Again", "rev.hard": "Hard", "rev.good": "Good", "rev.easy": "Easy",
  "speak": "Listen", "delete": "Delete",

  "words.loading": "Loading words…", "words.title": "My words",
  "words.search": "Search words and translations", "words.none": "Nothing found",
  "words.empty": "Nothing here yet. Add your first word by voice!", "words.confirmDelete": "Delete “{word}”?",

  "prof.hello": "Hi!", "prof.premiumUntil": "Premium until {d}", "prof.free": "Free plan",
  "prof.words": "words", "prof.due": "to review", "prof.today": "reviewed today", "prof.streak": "day streak",
  "prof.premiumActive": "Premium is active", "prof.premiumThanks": "No limits until {d}. Thanks for being with us!",
  "prof.todayFree": "Today on the free plan", "prof.goPremium": "Premium, no limits",
  "prof.promoWaiting": "Your promo code is waiting: +{n} days come with Premium",
  "prof.learning": "I'm learning", "prof.base": "App language", "prof.baseHint": "Translations, explanations and {mascot}'s replies",
  "quota.word": "AI words", "quota.voice": "Voice words", "quota.chat": "Chat with Rimy", "quota.check": "AI answer checks",

  "promo.title": "Promo code", "promo.hint": "A code from the Rimy team adds days to Premium", "promo.apply": "Apply",

  "pay.perk1": "Unlimited AI words and voice", "pay.perk2": "Unlimited AI answer checks",
  "pay.perk3": "Conversation practice with {mascot}", "pay.perk4": "All languages at once",
  "pay.promoAdds": "Your promo code adds +{n} more days", "pay.subscribe": "Subscribe for {n} Stars a month",
  "pay.havePromo": "I have a promo code", "pay.notNow": "Not now", "pay.reviewFree": "Reviewing cards is always free",
};

const DICTS: Record<Locale, Record<Key, string>> = { ru, uz, en };
const DATE_LOCALE: Record<Locale, string> = { ru: "ru-RU", uz: "uz-UZ", en: "en-GB" };

function guess(): Locale {
  const code = window.Telegram?.WebApp?.initDataUnsafe?.user?.language_code ?? navigator.language ?? "ru";
  return code.startsWith("uz") ? "uz" : code.startsWith("en") ? "en" : "ru";
}

let current: Locale = guess();

/** Called by App whenever /api/me tells the base language. */
export function setLocale(code: string): void {
  current = code === "uz" || code === "en" ? code : "ru";
  document.documentElement.lang = current;
}

export function t(key: Key, vars: Record<string, string | number> = {}): string {
  let text = DICTS[current][key] ?? ru[key];
  for (const [name, value] of Object.entries(vars)) text = text.split(`{${name}}`).join(String(value));
  return text;
}

export const formatDate = (iso: string): string => new Date(iso).toLocaleDateString(DATE_LOCALE[current]);
