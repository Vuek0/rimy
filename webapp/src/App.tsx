import { useCallback, useEffect, useState } from "react";
import { api, LimitError, type Me } from "./api";
import { initData, tg } from "./telegram";
import { AddScreen } from "./screens/AddScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { WordsScreen } from "./screens/WordsScreen";
import { ProfileScreen } from "./screens/ProfileScreen";
import { Paywall } from "./screens/Paywall";
import { AdminScreen } from "./screens/AdminScreen";

type Tab = "add" | "review" | "words" | "profile" | "admin";

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: "add", icon: "➕", label: "Добавить" },
  { id: "review", icon: "📚", label: "Повторить" },
  { id: "words", icon: "📋", label: "Слова" },
  { id: "profile", icon: "🦥", label: "Профиль" },
];
const ADMIN_TAB = { id: "admin" as Tab, icon: "📊", label: "Дашборд" };

export function App() {
  const [tab, setTab] = useState<Tab>("add");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  const [paywall, setPaywall] = useState<string | null>(null);

  const refresh = useCallback(() => api.me().then(setMe).catch((e: Error) => setError(e.message)), []);

  useEffect(() => {
    if (!initData()) {
      setError("Открой приложение из Telegram-бота 🙂");
      return;
    }
    refresh();
    api.track("app_open");
  }, [refresh]);

  /** Every screen reports errors here: a used-up free limit opens the paywall. */
  const onError = useCallback((e: unknown) => {
    if (e instanceof LimitError) {
      setPaywall(e.message);
      api.track("paywall_view", { reason: e.kind });
    } else {
      tg?.showAlert((e as Error).message) ?? alert((e as Error).message);
    }
  }, []);

  if (error) return <div className="center muted">{error}</div>;
  if (!me) return <div className="center muted">Загружаю… 🦥</div>;

  return (
    <div className="app">
      <main className="screen">
        {tab === "add" && <AddScreen me={me} onError={onError} onSaved={refresh} />}
        {tab === "review" && <ReviewScreen onError={onError} onChange={refresh} />}
        {tab === "words" && <WordsScreen onError={onError} onChange={refresh} />}
        {tab === "profile" && (
          <ProfileScreen me={me} onError={onError} onChange={refresh} onPremium={() => setPaywall("")} />
        )}
        {tab === "admin" && me.is_admin && <AdminScreen onError={onError} />}
      </main>
      <nav className="tabs">
        {(me.is_admin ? [...TABS, ADMIN_TAB] : TABS).map((t) => (
          <button key={t.id} className={t.id === tab ? "tab active" : "tab"} onClick={() => setTab(t.id)}>
            <span className="tab-icon">{t.icon}</span>
            {t.label}
            {t.id === "review" && me.stats.due > 0 && <span className="badge">{me.stats.due}</span>}
          </button>
        ))}
      </nav>
      {paywall !== null && <Paywall me={me} reason={paywall} onClose={() => setPaywall(null)} onPaid={refresh} />}
    </div>
  );
}
