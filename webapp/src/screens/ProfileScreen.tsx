import { api, type Me } from "../api";

interface Props { me: Me; onError: (e: unknown) => void; onChange: () => void; onPremium: () => void }

const QUOTA_NAMES: Record<string, string> = {
  word: "AI-слова", voice: "Голосовые", chat: "Сообщения маскоту", check: "AI-проверки ответов",
};

export function ProfileScreen({ me, onError, onChange, onPremium }: Props) {
  const change = (job: () => Promise<unknown>) => async () => {
    try {
      await job();
      onChange();
    } catch (e) {
      onError(e);
    }
  };

  return (
    <div className="stack">
      <h1>Привет{me.first_name ? `, ${me.first_name}` : ""}! 🦥</h1>

      <div className="stats">
        <div className="stat"><b>{me.stats.words}</b><span>слов</span></div>
        <div className="stat"><b>{me.stats.due}</b><span>к повторению</span></div>
        <div className="stat"><b>{me.stats.reviewed_today}</b><span>сегодня</span></div>
        <div className="stat"><b>🔥 {me.stats.streak}</b><span>дней подряд</span></div>
      </div>

      <div className="card">
        {me.premium ? (
          <p>⭐ Premium активен до <b>{new Date(me.premium_until!).toLocaleDateString("ru-RU")}</b></p>
        ) : (
          <>
            <h2>Бесплатный тариф</h2>
            {Object.values(me.quotas).map((q) => (
              <div key={q.kind} className="quota">
                <span>{QUOTA_NAMES[q.kind]}</span>
                <span className="muted">{q.used} / {q.limit}</span>
                <div className="bar"><div style={{ width: `${Math.min(100, (q.used / q.limit) * 100)}%` }} /></div>
              </div>
            ))}
            <button className="primary wide" onClick={onPremium}>⭐ Premium - без лимитов</button>
          </>
        )}
      </div>

      <div className="card">
        <h2>Учу язык</h2>
        <div className="chips">
          {me.langs.map((l) => (
            <button key={l.code} className={l.code === me.lang ? "chip active" : "chip"} onClick={change(() => api.setLang(l.code))}>
              {l.flag} {l.name}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>Язык общения</h2>
        <p className="hint">На нём будут переводы, объяснения и ответы {me.mascot}</p>
        <div className="chips">
          {me.base_langs.map((l) => (
            <button key={l.code} className={l.code === me.native_lang ? "chip active" : "chip"} onClick={change(() => api.setBase(l.code))}>
              {l.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
