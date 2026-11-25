import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft, Bell, BellOff, BookOpen, Check, ChevronRight, Clock, Crown, ExternalLink, Gift, Layers,
  Link2, Search, Sparkles, Star, type LucideIcon,
} from "lucide-react";
import { api, avatarUrl, type Person, type PersonProfile } from "../api";
import { haptic, tg } from "../telegram";
import { FullLoader } from "../ui";

const AI_LABELS: Record<string, string> = { word: "AI-слова", voice: "Голосовые", chat: "Сообщения Rimy", check: "AI-проверки" };

/** "5 мин назад", "3 ч назад", "вчера", then the date. */
function ago(iso: string | null): string {
  if (!iso) return "ни разу";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  if (min < 24 * 60) return `${Math.round(min / 60)} ч назад`;
  if (min < 48 * 60) return "вчера";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

const when = (iso: string) =>
  new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const displayName = (p: { first_name: string; username: string; id: number }) =>
  p.first_name || (p.username ? `@${p.username}` : `id ${p.id}`);

// At most a few photo requests at once: each one is a call to Telegram on the server.
let running = 0;
const waiting: (() => void)[] = [];
async function limited<T>(job: () => Promise<T>): Promise<T> {
  if (running >= 4) await new Promise<void>((go) => waiting.push(go));
  running++;
  try {
    return await job();
  } finally {
    running--;
    waiting.shift()?.();
  }
}

function Avatar({ id, name, size = 44 }: { id: number; name: string; size?: number }) {
  const [photo, setPhoto] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let alive = true;
    limited(() => avatarUrl(id))
      .then((u) => { url = u; if (alive) setPhoto(u); })
      .catch(() => undefined);
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [id]);
  return (
    <div className="avatar" style={{ width: size, height: size, borderRadius: size / 3, fontSize: size * 0.42 }}>
      {photo ? <img src={photo} alt="" /> : name.replace("@", "").slice(0, 1).toUpperCase() || "?"}
    </div>
  );
}

function Fact({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string | number }) {
  return (
    <div className="stat">
      <span className="stat-icon"><Icon size={18} /></span>
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

function Profile({ id, onBack, onError }: { id: number; onBack: () => void; onError: (e: unknown) => void }) {
  const [p, setP] = useState<PersonProfile | null>(null);
  useEffect(() => { api.person(id).then(setP).catch(onError); }, [id, onError]);

  if (!p) return <FullLoader text="Открываю профиль…" />;
  const name = displayName(p);
  const reached = p.funnel.filter((s) => s.at).length;
  const ai = Object.entries(p.ai_total).filter(([, n]) => n > 0);

  return (
    <div className="stack stagger">
      <button className="ghost back" onClick={onBack}><ArrowLeft size={18} /> Все люди</button>

      <div className="profile-head">
        <Avatar id={p.id} name={name} size={64} />
        <div style={{ minWidth: 0 }}>
          <h1 className="ellipsis">{name}</h1>
          <p className="muted">
            {p.username && <>@{p.username} · </>}id {p.id}
          </p>
          <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
            {p.premium && <span className="pill"><Crown size={12} /> Premium</span>}
            {p.ref && <span className="pill"><Link2 size={12} /> {p.ref}</span>}
            <span className="pill">{p.native_lang.name}</span>
          </div>
        </div>
      </div>

      {p.username && (
        <button className="wide" onClick={() => tg?.openTelegramLink?.(`https://t.me/${p.username}`)}>
          <ExternalLink size={16} /> Написать в Telegram
        </button>
      )}

      <div className="stats">
        <Fact icon={BookOpen} label="слов" value={p.stats.words} />
        <Fact icon={Layers} label="повторений" value={p.stats.reviews} />
        <Fact icon={Clock} label="был(а) в боте" value={ago(p.last_active_at)} />
        <Fact icon={Star} label="Stars заплачено" value={p.payments.reduce((sum, x) => sum + x.stars, 0)} />
      </div>

      <div className="card">
        <h3>Учит</h3>
        {p.decks.length === 0 ? <p className="hint">Ещё не выбрал(а) язык</p> : (
          <table className="table"><tbody>
            {p.decks.map((d) => (
              <tr key={d.code}><td>{d.flag} {d.name}</td><td className="num">{d.words} слов</td></tr>
            ))}
          </tbody></table>
        )}
        <p className="hint">
          К повторению сейчас: {p.stats.due} · последнее повторение {ago(p.stats.last_review_at)}
        </p>
      </div>

      <div className="card">
        <h3>Путь в продукте</h3>
        <p className="hint">Пройдено шагов: {reached} из {p.funnel.length}</p>
        <ul className="steps">
          {p.funnel.map((s) => (
            <li key={s.key} className={s.at ? "done" : ""}>
              <span className="step-dot">{s.at && <Check size={12} />}</span>
              <span>{s.label}</span>
              <span className="muted">{s.at ? when(s.at) : ""}</span>
            </li>
          ))}
        </ul>
      </div>

      {p.recent_words.length > 0 && (
        <div className="card">
          <h3>Последние слова</h3>
          <table className="table"><tbody>
            {p.recent_words.map((w, i) => (
              <tr key={i}>
                <td><b>{w.display}</b><div className="hint">{w.translation}</div></td>
                <td className="num muted" style={{ fontWeight: 600 }}>{ago(w.at)}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      )}

      <div className="card">
        <h3>Детали</h3>
        <table className="table"><tbody>
          <tr><td>Пришёл(ла)</td><td className="num">{when(p.created_at)}</td></tr>
          <tr><td>Premium</td><td className="num">{p.premium_until ? `до ${when(p.premium_until)}` : "нет"}</td></tr>
          <tr><td>Напоминания</td><td className="num">{p.reminders ? <Bell size={16} /> : <BellOff size={16} />}</td></tr>
          <tr><td>Разговорная практика</td><td className="num">{p.practice_mode ? "вкл" : "выкл"}</td></tr>
          <tr><td>Часовой пояс</td><td className="num">{p.timezone}</td></tr>
          {ai.map(([kind, n]) => (
            <tr key={kind}><td><Sparkles size={14} /> {AI_LABELS[kind] ?? kind}, всего</td><td className="num">{n}</td></tr>
          ))}
          {p.payments.map((x, i) => (
            <tr key={`pay${i}`}><td><Star size={14} /> Оплата {when(x.at)}</td><td className="num">{x.stars} ⭐</td></tr>
          ))}
          {p.promos.map((x) => (
            <tr key={x.code}>
              <td><Gift size={14} /> <span className="code">{x.code}</span></td>
              <td className="num">+{x.days} дн. {x.applied ? "применён" : "ждёт оплаты"}</td>
            </tr>
          ))}
        </tbody></table>
      </div>
    </div>
  );
}

/** Everyone who opened the bot, newest first, with search; tap a person to see their profile. */
export function AdminPeople({ onError }: { onError: (e: unknown) => void }) {
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<Person[] | null>(null);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const scrollY = useRef(0);

  const load = useCallback((q: string, more = false) => {
    api.people(q, more ? (people?.length ?? 0) : 0)
      .then((r) => { setTotal(r.total); setPeople((prev) => (more && prev ? [...prev, ...r.users] : r.users)); })
      .catch(onError);
  }, [onError, people?.length]);

  useEffect(() => {
    const timer = setTimeout(() => load(query), 250);  // wait for the typing to pause
    return () => clearTimeout(timer);
  }, [query]);  // eslint-disable-line react-hooks/exhaustive-deps

  // the app scrolls inside .screen, not the window: come back to the same place in the list
  const scroller = () => document.querySelector<HTMLElement>(".screen");
  const show = (id: number) => {
    haptic.tap();
    scrollY.current = scroller()?.scrollTop ?? 0;
    setOpen(id);
    scroller()?.scrollTo(0, 0);
  };
  const back = () => {
    setOpen(null);
    requestAnimationFrame(() => scroller()?.scrollTo(0, scrollY.current));
  };

  if (open !== null) return <Profile id={open} onBack={back} onError={onError} />;

  return (
    <div className="stack">
      <div className="search">
        <Search size={18} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Имя, @username, ref или id" />
      </div>
      {people === null ? <FullLoader text="Собираю людей…" /> : (
        <>
          <p className="hint">{query ? `Найдено: ${total}` : `Всего: ${total}`}</p>
          {people.length === 0 && <p className="hint">Никого не нашлось</p>}
          <div className="stack stagger" style={{ gap: 8 }}>
            {people.map((u) => (
              <button key={u.id} className="card person-row" onClick={() => show(u.id)}>
                <Avatar id={u.id} name={displayName(u)} />
                <div className="person-main">
                  <div className="row" style={{ gap: 6 }}>
                    <b className="ellipsis">{displayName(u)}</b>
                    {u.premium && <Crown size={14} color="var(--warn)" />}
                  </div>
                  <span className="hint ellipsis">
                    {u.username ? `@${u.username} · ` : ""}{u.words} слов · {ago(u.last_active_at)}
                    {u.ref ? ` · ${u.ref}` : ""}
                  </span>
                </div>
                <ChevronRight size={18} className="muted" />
              </button>
            ))}
          </div>
          {people.length < total && (
            <button className="wide" onClick={() => load(query, true)}>Показать ещё</button>
          )}
        </>
      )}
    </div>
  );
}
