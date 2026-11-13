import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import ja from './locales/ja.json'
import vi from './locales/vi.json'

export const LANGUAGE_STORAGE_KEY = 'phc_language'
const SUPPORTED_LANGUAGES = ['en', 'ja', 'vi']

const storedLanguage = localStorage.getItem(LANGUAGE_STORAGE_KEY)

i18next.use(initReactI18next).init({
  resources: { en: { translation: en }, ja: { translation: ja }, vi: { translation: vi } },
  lng: SUPPORTED_LANGUAGES.includes(storedLanguage) ? storedLanguage : 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export function setLanguage(lang) {
  i18next.changeLanguage(lang)
  localStorage.setItem(LANGUAGE_STORAGE_KEY, lang)
}

export default i18next
