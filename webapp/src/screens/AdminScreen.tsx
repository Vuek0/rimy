import { useCallback, useEffect, useState } from "react";
import {
  Activity, BarChart3, BookOpen, Copy, Crown, Gift, Layers, Plus, Power, Receipt, Star, UserPlus, Users, type LucideIcon,
} from "lucide-react";
import { api, type Dashboard, type Point, type Promo } from "../api";
import { haptic, tg } from "../telegram";
import { FullLoader } from "../ui";
import { AdminPeople } from "./AdminPeople";

const REFRESH_MS = 15_000;
const RANGES = [7, 14, 30];

const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });

const pct = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

/** One series per chart: daily bars, hover/tap shows the exact value. */
function BarChart({ title, points, unit, summary = "total" }: {
  title: string; points: Point[]; unit: string; summary?: "total" | "today";
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...points.map((p) => p.value));
  // daily actives can't be added up (the same person is active on many days): show today's value instead
  const headline = summary === "today" ? points[points.length - 1].value : points.reduce((sum, p) => sum + p.value, 0);
  const W = 320, H = 120, gap = 2;
  const bw = W / points.length;
  const shown = hover !== null ? points[hover] : null;

  return (
    <div className="card chart">
      <div className="chart-head">
        <h3>{title}</h3>
        <span className="chart-value">
          {shown ? (
            <>{dayLabel(shown.day)}: <b>{shown.value}</b> {unit}</>
          ) : (
            <>{summary === "today" ? "сегодня" : "всего"} <b>{headline}</b> {unit}</>
          )}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H + 18}`}
        role="img"
        aria-label={`${title}: ${points.map((p) => `${dayLabel(p.day)} ${p.value}`).join(", ")}`}
        onPointerLeave={() => setHover(null)}
      >
        <line x1="0" x2={W} y1={H} y2={H} className="chart-axis" />
        {points.map((p, i) => {
          const h = p.value === 0 ? 0 : Math.max(3, (p.value / max) * (H - 6));
          return (
            <g key={p.day} onPointerEnter={() => setHover(i)} onClick={() => setHover(i)}>
              {/* the hit target is the whole column, wider and taller than the bar */}
              <rect x={i * bw} y="0" width={bw} height={H} fill="transparent" />
              <rect
                x={i * bw + gap / 2}
                y={H - h}
                width={bw - gap}
                height={h}
                rx={Math.min(4, (bw - gap) / 2)}
                className={hover === i ? "chart-bar active" : "chart-bar"}
                style={{ animationDelay: `${i * 20}ms` }}
              />
            </g>
          );
        })}
        <text x="0" y={H + 14} className="chart-tick">{dayLabel(points[0].day)}</text>
        <text x={W} y={H + 14} textAnchor="end" className="chart-tick">сегодня</text>
      </svg>
    </div>
  );
}

function Kpi({ icon: Icon, value, label }: { icon: LucideIcon; value: string | number; label: string }) {
  return (
    <div className="stat">
      <span className="stat-icon"><Icon size={18} /></span>
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

/** Generate codes for the stand and see how many people used them. */
function PromoAdmin({ onError }: { onError: (e: unknown) => void }) {
  const [promos, setPromos] = useState<Promo[]>([]);
  const [days, setDays] = useState(30);
  const [maxUses, setMaxUses] = useState(100);
  const [custom, setCustom] = useState("");
  const [created, setCreated] = useState("");

  const load = useCallback(() => api.promos().then((r) => setPromos(r.promos)).catch(onError), [onError]);
  useEffect(() => { load(); }, [load]);

  const copy = (code: string) => {
    navigator.clipboard?.writeText(code).then(() => haptic.success()).catch(() => undefined);
    tg?.showAlert(`Код ${code} скопирован`);
  };

  const create = async () => {
    try {
      const res = await api.createPromo(days, maxUses, custom.trim());
      haptic.success();
      setCreated(res.code);
      setCustom("");
      load();
    } catch (e) {
      onError(e);
    }
  };

  const toggle = async (p: Promo) => {
    try {
      await api.setPromoActive(p.id, !p.active);
      load();
    } catch (e) {
      onError(e);
    }
  };

  return (
    <div className="card">
      <div className="row" style={{ gap: 10 }}>
        <span className="stat-icon" style={{ margin: 0 }}><Gift size={18} /></span>
        <div>
          <h3>Промокоды</h3>
          <p className="hint">Добавляют дни к оплаченному Premium</p>
        </div>
      </div>
      <div className="promo-new">
        <label>Дней Premium<input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} /></label>
        <label>Макс. человек (0 = все)<input type="number" min={0} value={maxUses} onChange={(e) => setMaxUses(Number(e.target.value))} /></label>
        <label className="full">Свой код (необязательно)<input className="code" value={custom} onChange={(e) => setCustom(e.target.value.toUpperCase())} placeholder="Авто: RIMY-XXXXXX" /></label>
        <button className="primary full" onClick={create} disabled={days < 1}><Plus size={18} /> Создать код</button>
      </div>
      {created && (
        <button className="notice ok enter" onClick={() => copy(created)} style={{ justifyContent: "flex-start" }}>
          <Copy size={16} /> <span>Готово: <span className="code">{created}</span> (нажми, чтобы скопировать)</span>
        </button>
      )}
      {promos.length > 0 && (
        <table className="table">
          <tbody>
            {promos.map((p) => (
              <tr key={p.id} className={p.active ? "" : "off"}>
                <td>
                  <button className="icon" onClick={() => copy(p.code)} style={{ padding: 0, color: "var(--text)" }}>
                    <span className="code">{p.code}</span> <Copy size={14} />
                  </button>
                  <div className="hint">+{p.days} дн. · применён {p.applied} из {p.used}</div>
                </td>
                <td className="num">{p.used}{p.max_uses ? ` / ${p.max_uses}` : ""}</td>
                <td className="num" style={{ width: 44 }}>
                  <button className="icon" onClick={() => toggle(p)} aria-label={p.active ? "Выключить" : "Включить"}>
                    <Power size={18} color={p.active ? "var(--ok)" : "var(--muted)"} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** The team's live dashboard (admins only): refreshes itself every 15 s, made to stay open on the stand's screen. */
export function AdminScreen({ onError }: { onError: (e: unknown) => void }) {
  const [view, setView] = useState<"numbers" | "people">("numbers");
  const switcher = (
    <div className="chips">
      <button className={view === "numbers" ? "chip active" : "chip"} onClick={() => setView("numbers")}>
        <BarChart3 size={16} /> Цифры
      </button>
      <button className={view === "people" ? "chip active" : "chip"} onClick={() => setView("people")}>
        <Users size={16} /> Люди
      </button>
    </div>
  );
  return (
    <div className="stack">
      {switcher}
      {view === "numbers" ? <Numbers onError={onError} /> : <AdminPeople onError={onError} />}
    </div>
  );
}

function Numbers({ onError }: { onError: (e: unknown) => void }) {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<Dashboard | null>(null);

  const load = useCallback(() => api.dashboard(days).then(setData).catch(onError), [days, onError]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  if (!data) return <FullLoader text="Считаю цифры…" />;

  const t = data.totals;
  const start = data.funnel[0]?.users ?? 0;
  const updated = new Date(data.generated_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <div className="stack">
      <div className="row admin-head enter">
        <h1>Rimy live</h1>
        <span className="live">обновлено {updated}</span>
      </div>

      <div className="kpis stagger">
        <Kpi icon={Users} value={t.users} label="пользователей всего" />
        <Kpi icon={UserPlus} value={`+${t.new_today}`} label="новых сегодня" />
        <Kpi icon={Activity} value={t.active_today} label="активны сегодня" />
        <Kpi icon={BookOpen} value={t.words} label="слов добавлено" />
        <Kpi icon={Layers} value={t.reviews} label="повторений" />
        <Kpi icon={Crown} value={t.premium} label="Premium активно" />
        <Kpi icon={Receipt} value={t.payments} label="оплат" />
        <Kpi icon={Star} value={t.stars} label="Stars получено" />
      </div>

      <div className="chips">
        {RANGES.map((r) => (
          <button key={r} className={r === days ? "chip active" : "chip"} onClick={() => setDays(r)}>
            {r} дней
          </button>
        ))}
      </div>

      <div className="stack stagger" key={days}>
        <BarChart title="Новые пользователи" points={data.series.new_users} unit="чел." />
        <BarChart title="Активные пользователи" points={data.series.active_users} unit="чел." summary="today" />
        <BarChart title="Добавлено слов" points={data.series.words} unit="слов" />
        <BarChart title="Повторения карточек" points={data.series.reviews} unit="повторений" />
        <BarChart title="AI-запросы" points={data.series.ai} unit="запросов" />
      </div>

      <div className="card">
        <h3>Воронка за {data.days} дн.</h3>
        <p className="hint">Уникальные пользователи на каждом шаге, % от открывших бота</p>
        {data.funnel.map((step) => (
          <div key={step.key} className="funnel-row">
            <div className="funnel-label">
              <span>{step.label}</span>
              <span><b>{step.users}</b> <span className="muted">{pct(step.users, start)}%</span></span>
            </div>
            <div className="bar"><div style={{ width: `${pct(step.users, start)}%` }} /></div>
          </div>
        ))}
      </div>

      <PromoAdmin onError={onError} />

      <div className="card">
        <h3>AI сегодня</h3>
        <table className="table">
          <tbody>
            {data.ai_today.map((row) => (
              <tr key={row.kind}><td>{row.label}</td><td className="num">{row.count}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Лиды по ссылкам</h3>
        {data.refs.length === 0 ? (
          <p className="hint">Пока никого. Ссылка для QR: t.me/rimy_ai_bot?start=ref_имя</p>
        ) : (
          <table className="table">
            <tbody>
              {data.refs.map((row) => (
                <tr key={row.ref}><td>{row.ref}</td><td className="num">{row.users}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
