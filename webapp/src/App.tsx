import { useCallback, useEffect, useState } from "react";
import { api, ApiError, hasCredential, openTicks } from "./api";
import { Apex } from "./components/Apex";
import { Board } from "./components/Board";
import { Feed } from "./components/Feed";
import { Login } from "./components/Login";
import { Positions } from "./components/Positions";
import { TokenPage } from "./components/TokenPage";
import { money, signed } from "./format";
import { bootTelegram, tg } from "./telegram";
import type { FeedToken, MarketMood, Me, Position, Tick, Trade } from "./types";

type Tab = "feed" | "positions" | "apex" | "board";

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [gate, setGate] = useState<"loading" | "in" | "login" | "denied">("loading");
  const [denyMsg, setDenyMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("feed");
  const [contract, setContract] = useState<string | null>(null);
  const [tokens, setTokens] = useState<FeedToken[]>([]);
  const [scanning, setScanning] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);
  const [unrealized, setUnrealized] = useState(0);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tick, setTick] = useState<Tick | null>(null);
  const [install, setInstall] = useState<BeforeInstallPromptEvent | null>(null);
  const [mood, setMood] = useState<MarketMood | null>(null);

  const refreshBook = useCallback(async () => {
    const [pos, hist, who] = await Promise.all([api.positions(), api.history(), api.me()]);
    setPositions(pos.positions);
    setUnrealized(pos.unrealized_pnl);
    setTrades(hist.trades);
    setMe(who);
  }, []);

  const loadFeed = useCallback(async (refresh = false) => {
    setScanning(true);
    try {
      const res = await api.feed(refresh);
      setTokens(res.tokens);
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    bootTelegram();
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setInstall(e as BeforeInstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  useEffect(() => {
    if (!hasCredential()) {
      setGate("login");
      return;
    }
    api.me()
      .then(async (who) => {
        setMe(who);
        setGate("in");
        await Promise.all([
          loadFeed(false),
          refreshBook(),
          api.mood().then((m) => setMood(m.mood)).catch(() => setMood(null)),
        ]);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          setDenyMsg(err.message);
          setGate("denied");
        } else if (err instanceof ApiError && (err.status === 401 || err.status === 0)) {
          setGate("login");
        } else {
          setDenyMsg(err instanceof Error ? err.message : "Couldn't open the terminal");
          setGate("denied");
        }
      });
  }, [loadFeed, refreshBook]);

  useEffect(() => {
    if (gate !== "in") return;
    let stop = () => {};
    let timer = 0;
    const connect = () => {
      stop = openTicks(
        (next) => {
          setTick(next);
          setPositions(next.positions);
          setUnrealized(next.unrealized_pnl);
        },
        () => {
          timer = window.setTimeout(connect, 4000);
        },
      );
    };
    connect();
    return () => {
      stop();
      window.clearTimeout(timer);
    };
  }, [gate]);

  useEffect(() => {
    const app = tg();
    if (!app) return;
    const back = () => setContract(null);
    if (contract) {
      app.BackButton.show();
      app.BackButton.onClick(back);
    } else {
      app.BackButton.hide();
    }
    return () => app.BackButton.offClick(back);
  }, [contract]);

  if (gate === "loading") {
    return (
      <div className="app-shell grid place-items-center text-mute text-sm">
        Connecting to APEX…
      </div>
    );
  }
  if (gate === "login" || gate === "denied") {
    return (
      <div className="app-shell">
        <Login
          denied={gate === "denied"}
          message={denyMsg}
          onAuthed={(who) => {
            setMe(who);
            setGate("in");
            void loadFeed(false);
            void refreshBook();
          }}
        />
      </div>
    );
  }

  const balance = tick?.balance ?? me?.balance;
  const pnl = tick?.realized_pnl ?? me?.realized_pnl ?? 0;

  return (
    <div className="app-shell">
      <header className="px-4 pt-[max(12px,env(safe-area-inset-top))] pb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold tracking-[0.18em]">APEX</span>
          <span className="chip">Paper</span>
          {mood && (
            <span className={`chip ${mood.label === "COLD" ? "text-loss" : mood.label === "HOT" ? "text-gain" : "text-cyan"}`}>
              {mood.label} {mood.score}
            </span>
          )}
        </div>
        <div className="text-right">
          <div className="num text-sm">{money(balance)}</div>
          <div className={pnl >= 0 ? "text-gain num text-[11px]" : "text-loss num text-[11px]"}>
            {signed(pnl)} realized
          </div>
        </div>
      </header>
      {install && !contract && (
        <button
          className="mx-4 mb-2 text-left text-xs text-cyan"
          onClick={() => {
            void install.prompt();
            setInstall(null);
          }}
        >
          Install APEX on this device
        </button>
      )}
      <main className="scroll">
        {contract ? (
          <TokenPage
            contract={contract}
            quickBuy={me?.quick_buy_amount || 100}
            balanceSet={Boolean(me?.balance_set)}
            onBack={() => setContract(null)}
            onChanged={(patch) => {
              if (patch?.balance != null) {
                setMe((current) => (current ? { ...current, balance: patch.balance ?? current.balance } : current));
                setTick((current) => (current ? { ...current, balance: patch.balance ?? current.balance } : current));
              }
              void refreshBook();
            }}
          />
        ) : tab === "feed" ? (
          <Feed tokens={tokens} loading={scanning} onOpen={setContract} onRefresh={() => { void loadFeed(true); }} />
        ) : tab === "positions" ? (
          <Positions rows={positions} unrealized={unrealized} trades={trades} onOpen={setContract} />
        ) : tab === "apex" ? (
          <Apex onChanged={() => { void refreshBook(); }} />
        ) : (
          <Board />
        )}
      </main>
      <nav className="nav">
        <Nav id="feed" tab={tab} setTab={(id) => { setContract(null); setTab(id); }} label="Feed" />
        <Nav id="positions" tab={tab} setTab={(id) => { setContract(null); setTab(id); }} label="Book" />
        <Nav id="apex" tab={tab} setTab={(id) => { setContract(null); setTab(id); }} label="APEX" />
        <Nav id="board" tab={tab} setTab={(id) => { setContract(null); setTab(id); }} label="Board" />
      </nav>
    </div>
  );
}

function Nav({ id, tab, setTab, label }: { id: Tab; tab: Tab; setTab: (t: Tab) => void; label: string }) {
  return (
    <button className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
      {label}
    </button>
  );
}

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
}
