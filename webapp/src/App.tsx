import { useCallback, useEffect, useState } from "react";
import { BarChart3, BookOpen, Layers, PlusCircle, UserRound, type LucideIcon } from "lucide-react";
import { api, LimitError, type Me } from "./api";
import { initData, tg } from "./telegram";
import { AddScreen } from "./screens/AddScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { WordsScreen } from "./screens/WordsScreen";
import { ProfileScreen } from "./screens/ProfileScreen";
import { Paywall } from "./screens/Paywall";
import { AdminScreen } from "./screens/AdminScreen";
import { FullLoader } from "./ui";
import { setLocale, t } from "./i18n";

type Tab = "add" | "review" | "words" | "profile" | "admin";

const TABS: { id: Tab; icon: LucideIcon }[] = [
  { id: "add", icon: PlusCircle },
  { id: "review", icon: Layers },
  { id: "words", icon: BookOpen },
  { id: "profile", icon: UserRound },
];
const ADMIN_TAB = { id: "admin" as Tab, icon: BarChart3 };

export function App() {
  const [tab, setTab] = useState<Tab>("add");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  const [paywall, setPaywall] = useState<string | null>(null);

  const refresh = useCallback(() => api.me().then((m) => { setLocale(m.native_lang); setMe(m); }).catch((e: Error) => setError(e.message)), []);

  useEffect(() => {
    if (!initData()) {
      setError(t("app.openFromBot"));
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
  if (!me) return <FullLoader text={t("app.loading")} />;

  const tabs = me.is_admin ? [...TABS, ADMIN_TAB] : TABS;
  return (
    <div className="app">
      {/* key={tab}: each screen plays its entrance animation when opened */}
      <main className="screen" key={tab}>
        {tab === "add" && <AddScreen me={me} onError={onError} onSaved={refresh} />}
        {tab === "review" && <ReviewScreen onError={onError} onChange={refresh} />}
        {tab === "words" && <WordsScreen onError={onError} onChange={refresh} />}
        {tab === "profile" && (
          <ProfileScreen me={me} onError={onError} onChange={refresh} onPremium={() => setPaywall("")} />
        )}
        {tab === "admin" && me.is_admin && <AdminScreen onError={onError} />}
      </main>
      <nav className="tabs">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.id} className={item.id === tab ? "tab active" : "tab"} onClick={() => setTab(item.id)}>
              <span className="tab-icon"><Icon size={21} strokeWidth={item.id === tab ? 2.4 : 2} /></span>
              {t(`tab.${item.id}`)}
              {item.id === "review" && me.stats.due > 0 && <span className="badge">{me.stats.due}</span>}
            </button>
          );
        })}
      </nav>
      {paywall !== null && <Paywall me={me} reason={paywall} onClose={() => setPaywall(null)} onPaid={refresh} />}
    </div>
  );
}
