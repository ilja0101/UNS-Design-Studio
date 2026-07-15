// Onboarding flag: whether the operator has completed or skipped the quick-start
// wizard. Persisted in localStorage so first-time visitors land on /start while
// returning users go straight to the UNS Hub. The wizard stays reachable from
// the sidebar regardless.
const KEY = "uds.onboarded";

export function isOnboarded(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function markOnboarded(): void {
  try {
    localStorage.setItem(KEY, "1");
  } catch {
    /* storage unavailable — the wizard simply shows again next visit */
  }
}
