export function tg(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

export function bootTelegram(): void {
  const app = tg();
  if (!app) return;
  app.ready();
  app.expand();
  const tp = app.themeParams || {};
  const root = document.documentElement;
  const bg = tp.bg_color || "#07090d";
  if (tp.bg_color) root.style.setProperty("--bg", tp.bg_color);
  if (tp.secondary_bg_color) root.style.setProperty("--bg-elev", tp.secondary_bg_color);
  if (tp.section_bg_color) root.style.setProperty("--bg-elev-2", tp.section_bg_color);
  if (tp.text_color) root.style.setProperty("--text", tp.text_color);
  if (tp.hint_color) root.style.setProperty("--muted", tp.hint_color);
  if (tp.button_color) root.style.setProperty("--cyan", tp.button_color);
  try {
    app.setHeaderColor?.(bg);
    app.setBackgroundColor?.(bg);
  } catch {
    /* older Telegram clients */
  }
}

export function haptic(kind: "light" | "success" | "error"): void {
  const hf = tg()?.HapticFeedback;
  if (!hf) return;
  if (kind === "success") hf.notificationOccurred("success");
  else if (kind === "error") hf.notificationOccurred("error");
  else hf.impactOccurred("light");
}

export function initData(): string {
  return tg()?.initData || "";
}
