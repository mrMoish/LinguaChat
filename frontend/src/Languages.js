// Список языков для онбординга: популярные (кнопки) + полный список (поиск).
// code — ISO 639-1 (+ региональный суффикс для локале-вариантов, используется как ключ языка в БД)
// locale — BCP-47, используется для TTS (speechSynthesis) и STT (SpeechRecognition)
// name — отображаемое имя на русском

export const LANGUAGES = [
  // Популярные
  { code: 'zh', locale: 'zh-CN', name: 'Китайский', popular: true },
  { code: 'es', locale: 'es-ES', name: 'Испанский', popular: true },
  { code: 'es-AR', locale: 'es-AR', name: 'Испанский (Аргентина)', popular: true },
  { code: 'es-MX', locale: 'es-MX', name: 'Испанский (Мексика)', popular: true },
  { code: 'en', locale: 'en-US', name: 'Английский', popular: true },
  { code: 'en-GB', locale: 'en-GB', name: 'Английский (Британия)', popular: true },
  { code: 'fr', locale: 'fr-FR', name: 'Французский', popular: true },
  { code: 'de', locale: 'de-DE', name: 'Немецкий', popular: true },
  { code: 'it', locale: 'it-IT', name: 'Итальянский', popular: true },
  { code: 'pt', locale: 'pt-PT', name: 'Португальский', popular: true },
  { code: 'pt-BR', locale: 'pt-BR', name: 'Португальский (Бразилия)', popular: true },
  { code: 'ja', locale: 'ja-JP', name: 'Японский', popular: true },
  { code: 'ko', locale: 'ko-KR', name: 'Корейский', popular: true },
  { code: 'tr', locale: 'tr-TR', name: 'Турецкий', popular: true },
  { code: 'ar', locale: 'ar-SA', name: 'Арабский', popular: true },

  // Остальные — только через поиск
  { code: 'nl', locale: 'nl-NL', name: 'Нидерландский' },
  { code: 'sv', locale: 'sv-SE', name: 'Шведский' },
  { code: 'no', locale: 'nb-NO', name: 'Норвежский' },
  { code: 'da', locale: 'da-DK', name: 'Датский' },
  { code: 'fi', locale: 'fi-FI', name: 'Финский' },
  { code: 'pl', locale: 'pl-PL', name: 'Польский' },
  { code: 'cs', locale: 'cs-CZ', name: 'Чешский' },
  { code: 'sk', locale: 'sk-SK', name: 'Словацкий' },
  { code: 'hu', locale: 'hu-HU', name: 'Венгерский' },
  { code: 'ro', locale: 'ro-RO', name: 'Румынский' },
  { code: 'bg', locale: 'bg-BG', name: 'Болгарский' },
  { code: 'el', locale: 'el-GR', name: 'Греческий' },
  { code: 'uk', locale: 'uk-UA', name: 'Украинский' },
  { code: 'ru', locale: 'ru-RU', name: 'Русский' },
  { code: 'he', locale: 'he-IL', name: 'Иврит' },
  { code: 'hi', locale: 'hi-IN', name: 'Хинди' },
  { code: 'th', locale: 'th-TH', name: 'Тайский' },
  { code: 'vi', locale: 'vi-VN', name: 'Вьетнамский' },
  { code: 'id', locale: 'id-ID', name: 'Индонезийский' },
  { code: 'ms', locale: 'ms-MY', name: 'Малайский' },
  { code: 'fil', locale: 'fil-PH', name: 'Филиппинский' },
  { code: 'zh-TW', locale: 'zh-TW', name: 'Китайский (Тайвань)' },
  { code: 'fr-CA', locale: 'fr-CA', name: 'Французский (Канада)' },
  { code: 'de-AT', locale: 'de-AT', name: 'Немецкий (Австрия)' },
  { code: 'es-CO', locale: 'es-CO', name: 'Испанский (Колумбия)' },
  { code: 'es-CL', locale: 'es-CL', name: 'Испанский (Чили)' },
  { code: 'ca', locale: 'ca-ES', name: 'Каталанский' },
  { code: 'sr', locale: 'sr-RS', name: 'Сербский' },
  { code: 'hr', locale: 'hr-HR', name: 'Хорватский' },
  { code: 'sl', locale: 'sl-SI', name: 'Словенский' },
  { code: 'lt', locale: 'lt-LT', name: 'Литовский' },
  { code: 'lv', locale: 'lv-LV', name: 'Латышский' },
  { code: 'et', locale: 'et-EE', name: 'Эстонский' },
  { code: 'fa', locale: 'fa-IR', name: 'Персидский' },
  { code: 'ur', locale: 'ur-PK', name: 'Урду' },
  { code: 'bn', locale: 'bn-BD', name: 'Бенгальский' },
  { code: 'ta', locale: 'ta-IN', name: 'Тамильский' },
  { code: 'te', locale: 'te-IN', name: 'Телугу' },
  { code: 'mr', locale: 'mr-IN', name: 'Маратхи' },
  { code: 'sw', locale: 'sw-KE', name: 'Суахили' },
  { code: 'az', locale: 'az-AZ', name: 'Азербайджанский' },
  { code: 'kk', locale: 'kk-KZ', name: 'Казахский' },
  { code: 'uz', locale: 'uz-UZ', name: 'Узбекский' },
  { code: 'ka', locale: 'ka-GE', name: 'Грузинский' },
  { code: 'hy', locale: 'hy-AM', name: 'Армянский' },
  { code: 'is', locale: 'is-IS', name: 'Исландский' },
  { code: 'ga', locale: 'ga-IE', name: 'Ирландский' },
  { code: 'mt', locale: 'mt-MT', name: 'Мальтийский' },
  { code: 'af', locale: 'af-ZA', name: 'Африкаанс' },
  { code: 'am', locale: 'am-ET', name: 'Амхарский' },
  { code: 'km', locale: 'km-KH', name: 'Кхмерский' },
  { code: 'lo', locale: 'lo-LA', name: 'Лаосский' },
  { code: 'my', locale: 'my-MM', name: 'Бирманский' },
  { code: 'ne', locale: 'ne-NP', name: 'Непальский' },
  { code: 'si', locale: 'si-LK', name: 'Сингальский' },
  { code: 'mn', locale: 'mn-MN', name: 'Монгольский' },
];

export function searchLanguages(query) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return LANGUAGES.filter(l => l.name.toLowerCase().includes(q));
}

export function popularLanguages() {
  return LANGUAGES.filter(l => l.popular);
}