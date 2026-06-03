export type AppLocale = "en-US" | "zh-CN";

export const LOCALE_STORAGE_KEY = "octopus.locale";

export const LOCALE_CHANGE_EVENT = "octopus:locale-change";

export function getLocalePreference(): AppLocale {
  if (typeof window === "undefined") return "zh-CN";
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  return stored === "en-US" ? "en-US" : "zh-CN";
}

export function setLocalePreference(locale: AppLocale): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    window.dispatchEvent(new CustomEvent(LOCALE_CHANGE_EVENT, { detail: locale }));
  }
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
}

export function initializeLocalePreference(): AppLocale {
  const locale = getLocalePreference();
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
  return locale;
}

export function isEnglishLocale(): boolean {
  return getLocalePreference() === "en-US";
}
