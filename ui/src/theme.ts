import { useEffect, useState } from "react";

const KEY = "uds-theme";

export function applyThemeFromStorage() {
  const t = localStorage.getItem(KEY);
  document.documentElement.classList.toggle("dark", t === "dark");
}

export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem(KEY, dark ? "dark" : "light");
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}
