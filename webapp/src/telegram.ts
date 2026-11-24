// Thin typed wrapper over window.Telegram.WebApp (loaded by telegram-web-app.js in index.html).

type Haptic = "light" | "medium" | "heavy";
type Notice = "success" | "error" | "warning";

interface TgWebApp {
  initData: string;
  initDataUnsafe: { user?: { first_name?: string; language_code?: string }; start_param?: string };
  colorScheme: "light" | "dark";
  ready(): void;
  expand(): void;
  openInvoice(url: string, cb?: (status: "paid" | "cancelled" | "failed" | "pending") => void): void;
  showAlert(message: string): void;
  openTelegramLink?(url: string): void;
  setHeaderColor?(color: string): void;
  setBackgroundColor?(color: string): void;
  setBottomBarColor?(color: string): void;
  HapticFeedback?: {
    impactOccurred(style: Haptic): void;
    notificationOccurred(type: Notice): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp: TgWebApp };
  }
}

export const tg: TgWebApp | undefined = window.Telegram?.WebApp;

export function initTelegram(): void {
  // Telegram's own theme (not the OS one) decides light/dark: styles.css reads :root[data-scheme]
  if (tg) document.documentElement.dataset.scheme = tg.colorScheme;
  // Telegram's header and background in the app's own palette, so the Mini App looks seamless
  const dark = tg?.colorScheme === "dark";
  try {
    tg?.setHeaderColor?.(dark ? "#111813" : "#f3f2ec");
    tg?.setBackgroundColor?.(dark ? "#111813" : "#f3f2ec");
    tg?.setBottomBarColor?.(dark ? "#1a241d" : "#ffffff");
  } catch {
    // older Telegram clients: keep their default colors
  }
  tg?.ready();
  tg?.expand();
}

export const initData = (): string => tg?.initData ?? "";

export const haptic = {
  tap: () => tg?.HapticFeedback?.impactOccurred("light"),
  success: () => tg?.HapticFeedback?.notificationOccurred("success"),
  error: () => tg?.HapticFeedback?.notificationOccurred("error"),
};
