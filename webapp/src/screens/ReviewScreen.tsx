import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle, Check, CheckCircle2, Eye, Mic, PartyPopper, RotateCcw, Square, ThumbsUp, Volume2, XCircle, Zap, Frown,
  type LucideIcon,
} from "lucide-react";
import { api, speak, type Card, type Check as CheckResult } from "../api";
import { haptic } from "../telegram";
import { useRecorder } from "../useRecorder";
import { FullLoader, Thinking } from "../ui";

interface Props { onError: (e: unknown) => void; onChange: () => void }

const RATINGS: { value: number; label: string; icon: LucideIcon; cls: string }[] = [
  { value: 1, label: "Снова", icon: RotateCcw, cls: "again" },
  { value: 2, label: "Трудно", icon: Frown, cls: "hard" },
  { value: 3, label: "Хорошо", icon: ThumbsUp, cls: "good" },
  { value: 4, label: "Легко", icon: Zap, cls: "easy" },
];
const VERDICT: Record<string, { text: string; icon: LucideIcon }> = {
  correct: { text: "Верно!", icon: CheckCircle2 },
  almost: { text: "Почти!", icon: AlertCircle },
  wrong: { text: "Не совсем", icon: XCircle },
};

/** FSRS review: front → answer by text / voice or just reveal → grade. */
export function ReviewScreen({ onError, onChange }: Props) {
  const [card, setCard] = useState<Card | null>(null);
  const [due, setDue] = useState(0);
  const [nextIn, setNextIn] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revealed, setRevealed] = useState(false);
  const [answer, setAnswer] = useState("");
  const [check, setCheck] = useState<CheckResult | null>(null);
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

  const submitCheck = async (job: () => Promise<CheckResult>) => {
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

  if (loading && !card) return <FullLoader text="Достаю карточки…" />;

  if (!card) {
    return (
      <div className="center stagger">
        <div className="celebrate"><PartyPopper size={44} /></div>
        <h2>{done ? `Повторено: ${done}. Ты супер!` : "На сейчас всё повторено"}</h2>
        {nextIn ? <p className="muted">Следующая карточка через {nextIn}</p> : <p className="muted">Добавь первые слова во вкладке «Добавить»</p>}
      </div>
    );
  }

  const w = card.word;
  const total = due + done;
  const verdict = check ? VERDICT[check.verdict] : undefined;
  const sayButton = (part: "word" | "example" = "word") => (
    <button className="icon" onClick={() => speak(w.id, part).catch(onError)} aria-label="Озвучить">
      <Volume2 size={part === "word" ? 22 : 18} />
    </button>
  );

  return (
    <div className="stack">
      <div className="stack-sm">
        <div className="spread">
          <span className="eyebrow">Повторение</span>
          <span className="hint">осталось {due}</span>
        </div>
        <div className="progress"><div style={{ width: `${total ? (done / total) * 100 : 0}%` }} /></div>
      </div>

      {/* key: every new card slides in */}
      <div className="card flashcard enter" key={card.id}>
        <div className="prompt">
          {card.prompt}
          {card.direction === "fwd" && sayButton()}
        </div>
        <p className="question">{card.question}</p>

        {!revealed && (
          <div className="stack-sm" style={{ marginTop: "auto" }}>
            <div className="input-row">
              <input
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && answer.trim() && submitCheck(() => api.answer(card.id, answer.trim()))}
                placeholder="Твой ответ"
                disabled={busy}
              />
              <button className="primary square" disabled={busy || !answer.trim()} onClick={() => submitCheck(() => api.answer(card.id, answer.trim()))} aria-label="Проверить">
                <Check size={20} />
              </button>
            </div>
            <div className="row">
              <button className={recorder.recording ? "primary" : ""} onClick={() => { haptic.tap(); recorder.toggle(); }} disabled={busy}>
                {recorder.recording ? <><Square size={16} fill="currentColor" /> Стоп</> : <><Mic size={18} /> Голосом</>}
              </button>
              <button className="ghost" onClick={() => setRevealed(true)} disabled={busy}>
                <Eye size={18} /> Показать
              </button>
            </div>
            {recorder.error && <p className="error">{recorder.error}</p>}
            {busy && <Thinking text="Проверяю" />}
          </div>
        )}

        {revealed && (
          <div className="stack-sm answer enter">
            {check && (
              <div className={`verdict ${check.verdict}`}>
                {verdict && <span className="verdict-title"><verdict.icon size={18} /> {verdict.text}</span>}
                {check.answer && <span>Твой ответ: <b>{check.answer}</b></span>}
                {check.comment && <p className="muted">{check.comment}</p>}
              </div>
            )}
            <h2 className="word-title">{w.display} {sayButton()}</h2>
            <p><b>{w.translations.join("; ")}</b></p>
            {w.example && (
              <p className="example">
                {w.example} {sayButton("example")}
                <br /><span className="muted">{w.example_translation}</span>
              </p>
            )}
            <p className="hint center-text" style={{ marginTop: 4 }}>Как легко вспомнилось?</p>
            <div className="grades stagger">
              {RATINGS.map((r) => (
                <button
                  key={r.value}
                  className={`grade ${r.cls}${check?.rating === r.value ? " suggested" : ""}`}
                  onClick={() => rate(r.value)}
                  disabled={busy}
                >
                  <r.icon size={20} />
                  {r.label}
                  <span className="small">{card.intervals[String(r.value)]}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
