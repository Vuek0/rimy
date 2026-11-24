import { useCallback, useEffect, useState } from "react";
import { api, type Dashboard, type Point } from "../api";

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

/** The team's live dashboard (admins only): refreshes itself every 15 s, made to stay open on the stand's screen. */
export function AdminScreen({ onError }: { onError: (e: unknown) => void }) {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<Dashboard | null>(null);

  const load = useCallback(() => api.dashboard(days).then(setData).catch(onError), [days, onError]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  if (!data) return <div className="center muted">Считаю цифры… 📊</div>;

  const t = data.totals;
  const start = data.funnel[0]?.users ?? 0;
  const updated = new Date(data.generated_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <div className="stack">
      <div className="row admin-head">
        <h1>📊 Rimy live</h1>
        <span className="live">● обновлено {updated}</span>
      </div>

      <div className="kpis">
        <div className="stat"><b>{t.users}</b><span>пользователей всего</span></div>
        <div className="stat"><b>+{t.new_today}</b><span>новых сегодня</span></div>
        <div className="stat"><b>{t.active_today}</b><span>активны сегодня</span></div>
        <div className="stat"><b>{t.words}</b><span>слов добавлено</span></div>
        <div className="stat"><b>{t.reviews}</b><span>повторений</span></div>
        <div className="stat"><b>{t.premium}</b><span>Premium активно</span></div>
        <div className="stat"><b>{t.payments}</b><span>оплат</span></div>
        <div className="stat"><b>{t.stars} ⭐</b><span>Stars получено</span></div>
      </div>

      <div className="chips">
        {RANGES.map((r) => (
          <button key={r} className={r === days ? "chip active" : "chip"} onClick={() => setDays(r)}>
            {r} дней
          </button>
        ))}
      </div>

      <BarChart title="Новые пользователи" points={data.series.new_users} unit="чел." />
      <BarChart title="Активные пользователи" points={data.series.active_users} unit="чел." summary="today" />
      <BarChart title="Добавлено слов" points={data.series.words} unit="слов" />
      <BarChart title="Повторения карточек" points={data.series.reviews} unit="повторений" />
      <BarChart title="AI-запросы" points={data.series.ai} unit="запросов" />

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
