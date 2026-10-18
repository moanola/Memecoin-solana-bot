/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_BOT_USERNAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
  header_bg_color?: string;
  section_bg_color?: string;
}

interface TelegramBackButton {
  show: () => void;
  hide: () => void;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
}

interface TelegramWebApp {
  initData: string;
  colorScheme?: "light" | "dark";
  themeParams: TelegramThemeParams;
  ready: () => void;
  expand: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
  };
  BackButton: TelegramBackButton;
}

interface Window {
  Telegram?: { WebApp?: TelegramWebApp };
  onTelegramAuth?: (user: Record<string, unknown>) => void;
}
