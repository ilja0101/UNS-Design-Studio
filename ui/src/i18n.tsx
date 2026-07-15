import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

// Lightweight bilingual layer, mirroring the UNS family convention. The suite
// is authored Dutch-first (the family vocabulary); English is the secondary.
// Rather than a keyed message catalogue, strings are translated inline at the
// call site: `t("Zoeken", "Search")`. Design Studio's chrome is English today,
// so only the Quick-start wizard consumes this — but the provider is app-wide
// so any page can opt in.

export type Lang = "nl" | "en";

interface I18nValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggle: () => void;
  /** Return the string for the current language: t(dutch, english). */
  t: (nl: string, en: string) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

const STORAGE_KEY = "uds-lang";

function initialLang(): Lang {
  const saved = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  return saved === "en" ? "en" : "nl";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* private mode / storage disabled — the in-memory choice still applies */
    }
    document.documentElement.lang = l;
  }, []);

  const value = useMemo<I18nValue>(
    () => ({
      lang,
      setLang,
      toggle: () => setLang(lang === "nl" ? "en" : "nl"),
      t: (nl: string, en: string) => (lang === "en" ? en : nl),
    }),
    [lang, setLang],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within an I18nProvider");
  return ctx;
}
