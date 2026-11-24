import { useCallback, useEffect, useState } from "react";
import { api, speak, type Card, type Check } from "../api";
import { haptic } from "../telegram";
import { useRecorder } from "../useRecorder";

interface Props { onError: (e: unknown) => void; onChange: () => void }

const RATINGS = [
  { value: 1, label: "Снова", emoji: "🔁" },
  { value: 2, label: "Трудно", emoji: "😬" },
  { value: 3, label: "Хорошо", emoji: "👍" },
  { value: 4, label: "Легко", emoji: "😎" },
];
const VERDICT: Record<string, string> = { correct: "✅ Верно!", almost: "🟡 Почти!", wrong: "❌ Не совсем" };

/** FSRS review: front → answer by text / voice or just reveal → grade. */
export function ReviewScreen({ onError, onChange }: Props) {
  const [card, setCard] = useState<Card | null>(null);
  const [due, setDue] = useState(0);
  const [nextIn, setNextIn] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revealed, setRevealed] = useState(false);
  const [answer, setAnswer] = useState("");
  const [check, setCheck] = useState<Check | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  const load = useCallback(async (after?: number) => {
    setLoading(true);
    try {
      const res = await api.nextCard(after);
      setCard(res.card);
      setDue(res.due);
      setNextIn(res.next_in ?? null);
      setRevealed(false);
      setCheck(null);
      setAnswer("");
    } catch (e) {
      onError(e);
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => { load(); }, [load]);

  const submitCheck = async (job: () => Promise<Check>) => {
    setBusy(true);
    try {
      const result = await job();
      setCheck(result);
      setRevealed(true);
      result.verdict === "correct" ? haptic.success() : result.verdict === "wrong" ? haptic.error() : haptic.tap();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  const onVoice = useCallback(
    (blob: Blob) => card && void submitCheck(() => api.answerVoice(card.id, blob)),
    [card],  // submitCheck only touches state setters and the stable onError
  );
  const recorder = useRecorder(onVoice);

  const rate = async (rating: number) => {
    if (!card) return;
    setBusy(true);
    try {
      await api.rate(card.id, rating);
      haptic.tap();
      setDone((d) => d + 1);
      onChange();
      await load(card.id);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  if (loading && !card) return <div className="center muted">Достаю карточки… 📚</div>;

  if (!card) {
    return (
      <div className="center stack">
        <div className="big-emoji">🎉</div>
        <h2>{done ? `Повторено: ${done}. Ты супер!` : "На сейчас всё повторено"}</h2>
        {nextIn ? <p className="muted">Следующая карточка через {nextIn}</p> : <p className="muted">Добавь первые слова во вкладке «Добавить»</p>}
      </div>
    );
  }

  const w = card.word;
  return (
    <div className="stack">
      <p className="muted">Осталось: {due}</p>
      <div className="card flashcard">
        <div className="prompt">
          {card.prompt}
          {card.direction === "fwd" && <button className="icon" onClick={() => speak(w.id).catch(onError)}>🔊</button>}
        </div>
        <p className="muted">{card.question}</p>

        {!revealed && (
          <div className="stack-sm">
            <div className="input-row">
              <input
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && answer.trim() && submitCheck(() => api.answer(card.id, answer.trim()))}
                placeholder="Твой ответ"
                disabled={busy}
              />
              <button className="primary" disabled={busy || !answer.trim()} onClick={() => submitCheck(() => api.answer(card.id, answer.trim()))}>✓</button>
            </div>
            <div className="row">
              <button className={recorder.recording ? "mic recording" : "mic"} onClick={recorder.toggle} disabled={busy}>
                {recorder.recording ? "⏹ Стоп" : "🎙 Ответить голосом"}
              </button>
              <button className="secondary" onClick={() => setRevealed(true)} disabled={busy}>👀 Показать</button>
            </div>
            {recorder.error && <p className="error">{recorder.error}</p>}
            {busy && <p className="muted center-text">Проверяю… 🔎</p>}
          </div>
        )}

        {revealed && (
          <div className="stack-sm answer">
            {check && (
              <div className={`verdict ${check.verdict}`}>
                <div>{check.answer && <>Твой ответ: <b>{check.answer}</b></>}</div>
                {VERDICT[check.verdict] && <b>{VERDICT[check.verdict]}</b>}
                {check.comment && <p className="muted">{check.comment}</p>}
              </div>
            )}
            <h2>
              {w.display} <button className="icon" onClick={() => speak(w.id).catch(onError)}>🔊</button>
            </h2>
            <p><b>{w.translations.join("; ")}</b></p>
            {w.example && (
              <p className="example">
                {w.example} <button className="icon" onClick={() => speak(w.id, "example").catch(onError)}>🔊</button>
                <br /><span className="muted">{w.example_translation}</span>
              </p>
            )}
            <div className="grades">
              {RATINGS.map((r) => (
                <button
                  key={r.value}
                  className={check?.rating === r.value ? "grade suggested" : "grade"}
                  onClick={() => rate(r.value)}
                  disabled={busy}
                >
                  {r.emoji} {r.label}
                  <span className="muted small">{card.intervals[String(r.value)]}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
