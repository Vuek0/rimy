import { useCallback, useState } from "react";
import { api, type Analysis, type Me } from "../api";
import { haptic } from "../telegram";
import { useRecorder } from "../useRecorder";

interface Props { me: Me; onError: (e: unknown) => void; onSaved: () => void }

/** Add a word by text or voice: AI analysis → pick the meaning(s) → save. */
export function AddScreen({ me, onError, onSaved }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [chosen, setChosen] = useState<number[]>([]);
  const [saved, setSaved] = useState("");

  const show = (a: Analysis) => {
    setAnalysis(a);
    setChosen(a.senses.length ? [0] : []);
    setSaved("");
    haptic.tap();
  };

  const run = async (job: () => Promise<Analysis>) => {
    setBusy(true);
    try {
      show(await job());
    } catch (e) {
      haptic.error();
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  // `run` only uses state setters and the stable onError, so the callback can stay the same across renders
  const onVoice = useCallback((blob: Blob) => void run(() => api.analyzeVoice(blob)), [onError]);
  const recorder = useRecorder(onVoice);

  const submit = (word = text) => word.trim() && run(() => api.analyze(word.trim()));

  const save = async () => {
    if (!analysis) return;
    const senses = chosen.map((i) => analysis.senses[i]);
    if (!senses.length) return;
    setBusy(true);
    try {
      const word = await api.saveWord({
        lemma: analysis.lemma,
        display: analysis.display,
        reading: analysis.reading,
        pos: analysis.pos,
        translations: senses.map((s) => s.translation),
        example: senses[0].example,
        example_translation: senses[0].example_translation,
        notes: analysis.notes,
      });
      haptic.success();
      setSaved(word.display);
      setAnalysis(null);
      setText("");
      onSaved();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (i: number) => setChosen((c) => (c.includes(i) ? c.filter((x) => x !== i) : [...c, i]));
  const lang = me.langs.find((l) => l.code === me.lang);
  const wordsLeft = me.quotas.word?.left;

  return (
    <div className="stack">
      <h1>Новое слово {lang?.flag}</h1>
      <p className="muted">Самый быстрый способ: нажми на микрофон и скажи слово, даже по-русски. {me.mascot} сам сделает карточку.</p>

      <button className={recorder.recording ? "mic recording" : "mic"} onClick={recorder.toggle} disabled={busy}>
        {recorder.recording ? "⏹ Остановить запись" : "🎙 Сказать слово голосом"}
      </button>
      {recorder.error && <p className="error">{recorder.error}</p>}

      <p className="hint center-text">или напиши текстом</p>
      <div className="input-row">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={`Слово на языке «${lang?.name ?? me.lang}» или по-русски`}
          maxLength={120}
          disabled={busy}
        />
        <button className="primary" onClick={() => submit()} disabled={busy || !text.trim()}>→</button>
      </div>
      {busy && <p className="muted center-text">{me.mascot} листает словарик… 📖</p>}
      {!me.premium && wordsLeft !== null && wordsLeft !== undefined && (
        <p className="hint">Бесплатных AI-слов сегодня: {wordsLeft}</p>
      )}

      {saved && <div className="card success">✅ «{saved}» в колоде! Повторим во вкладке «Повторить».</div>}

      {analysis && (
        <div className="card">
          {analysis.heard && <p className="muted">🎧 Расслышал: <b>{analysis.heard}</b></p>}
          {analysis.suggestions.length > 0 && (
            <div className="stack-sm">
              <p>Может, имелось в виду:</p>
              <div className="chips">
                {analysis.suggestions.map((s) => (
                  <button key={s} className="chip" onClick={() => { setText(s); submit(s); }}>✨ {s}</button>
                ))}
              </div>
            </div>
          )}
          {analysis.issues.map((i) => <p key={i} className="hint">• {i}</p>)}

          {analysis.senses.length === 0 ? (
            <p>Не нашёл такого слова 🤔 Проверь написание.</p>
          ) : (
            <>
              <h2>
                {analysis.display} {analysis.reading && <span className="muted">[{analysis.reading}]</span>}
              </h2>
              {analysis.pos && <p className="muted">{analysis.pos}</p>}
              <p className="muted">{analysis.senses.length > 1 ? "Выбери значения:" : "Значение:"}</p>
              {analysis.senses.map((s, i) => (
                <label key={i} className={chosen.includes(i) ? "sense chosen" : "sense"}>
                  <input type="checkbox" checked={chosen.includes(i)} onChange={() => toggle(i)} />
                  <div>
                    <b>{s.translation}</b> {s.note && <span className="muted">({s.note})</span>}
                    {s.example && <div className="example">{s.example}<br /><span className="muted">{s.example_translation}</span></div>}
                  </div>
                </label>
              ))}
              {analysis.notes && <p className="hint">💡 {analysis.notes}</p>}
              {analysis.duplicates.length > 0 && (
                <p className="hint">⚠️ Уже есть в колоде: {analysis.duplicates.flatMap((d) => d.translations).join("; ")}</p>
              )}
              <button className="primary wide" onClick={save} disabled={busy || !chosen.length}>✅ Сохранить</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
