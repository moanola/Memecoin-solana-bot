import { useEffect, useRef } from "react";
import { api, setSession } from "../api";
import type { Me } from "../types";

export function Login({
  denied,
  message,
  onAuthed,
}: {
  denied: boolean;
  message: string | null;
  onAuthed: (me: Me) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const onAuthedRef = useRef(onAuthed);
  onAuthedRef.current = onAuthed;
  const username = (import.meta.env.VITE_BOT_USERNAME || "").replace(/^@/, "");

  useEffect(() => {
    if (!username || !box.current) return;
    window.onTelegramAuth = (user) => {
      api.login(user)
        .then((res) => {
          setSession(res.token);
          onAuthedRef.current(res.user);
        })
        .catch((err: unknown) => {
          const el = box.current;
          if (el) {
            const note = document.createElement("div");
            note.className = "text-sm text-loss mt-3";
            note.textContent = err instanceof Error ? err.message : "Login failed";
            el.appendChild(note);
          }
        });
    };
    const script = document.createElement("script");
    script.async = true;
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", username);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-radius", "12");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    script.setAttribute("data-request-access", "write");
    box.current.appendChild(script);
    return () => {
      delete window.onTelegramAuth;
    };
  }, [username]);

  return (
    <div className="px-5 pt-16 max-w-[420px] mx-auto">
      <div className="text-[11px] tracking-[0.22em] uppercase text-cyan">Paper only</div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">APEX Terminal</h1>
      <p className="mt-3 text-sm text-mute leading-relaxed">
        Simulated Solana memecoin trading. No wallet, no private key, no on-chain swap.
        Open this from the bot with /terminal, or sign in with Telegram below.
      </p>
      {denied && (
        <div className="card p-3 mt-4 text-sm text-amber">
          {message || "Access required. Send /start to the bot and wait for approval."}
        </div>
      )}
      <div ref={box} className="mt-8" />
      {!username && (
        <div className="mt-6 text-sm text-mute">
          Outside Telegram, set <span className="num text-text">VITE_BOT_USERNAME</span> and register the
          site domain with BotFather so the login widget can appear.
        </div>
      )}
    </div>
  );
}
