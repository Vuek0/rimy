import { useCallback, useState } from "react";
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Headphones, Lightbulb, Mic, Sparkles, Square } from "lucide-react";
import { api, type Analysis, type Me } from "../api";
import { haptic, tg } from "../telegram";
import { useRecorder } from "../useRecorder";
import { Thinking } from "../ui";
import { t } from "../i18n";

interface Props { me: Me; onError: (e: unknown) => void; onSaved: () => void }

/** Add a word by voice (the main way) or text: AI analysis → pick the meaning(s) → save. */
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
      if (word.achievement) tg?.showAlert(t("toast.card"));  // a streak / vocabulary card was sent to the chat
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

  const toggle = (i: number) => {
    haptic.tap();
    setChosen((c) => (c.includes(i) ? c.filter((x) => x !== i) : [...c, i]));
  };
  const lang = me.langs.find((l) => l.code === me.lang);
  const wordsLeft = me.quotas.voice?.left;

  return (
    <div className="stack">
      <div className="hero stagger">
        <span className="eyebrow">{lang ? `${lang.flag} ${lang.name}` : t("add.eyebrow")}</span>
        <h1 style={{ whiteSpace: "pre-line" }}>{t("add.title")}</h1>
        <p className="muted">{t("add.sub", { mascot: me.mascot })}</p>
        <div className={recorder.recording ? "mic-wrap recording" : "mic-wrap"}>
          <span className="mic-ring" /><span className="mic-ring" /><span className="mic-ring" />
          <button
            className={recorder.recording ? "mic-btn recording" : "mic-btn"}
            onClick={() => { haptic.tap(); recorder.toggle(); }}
            disabled={busy}
            aria-label={recorder.recording ? t("add.micStop") : t("add.micStart")}
          >
            {recorder.recording ? <Square size={36} fill="currentColor" /> : <Mic size={42} strokeWidth={2.2} />}
          </button>
        </div>
        <span className="mic-label">{recorder.recording ? t("add.listening") : t("add.tap")}</span>
        {recorder.error && <p className="error">{recorder.error}</p>}
      </div>

      <div className="divider">{t("add.or")}</div>
      <div className="input-row enter">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={t("add.placeholder", { lang: lang?.name ?? me.lang })}
          maxLength={120}
          disabled={busy}
        />
        <button className="primary square" onClick={() => submit()} disabled={busy || !text.trim()} aria-label={t("add.analyze")}>
          <ArrowRight size={20} />
        </button>
      </div>
      {busy && <Thinking text={t("add.thinking", { mascot: me.mascot })} />}
      {!me.premium && wordsLeft !== null && wordsLeft !== undefined && (
        <p className="hint center-text">{t("add.voiceLeft", { n: wordsLeft })}</p>
      )}

      {saved && (
        <div className="notice ok enter">
          <CheckCircle2 size={18} />
          <span>{t("add.saved", { word: saved })}</span>
        </div>
      )}

      {analysis && (
        <div className="card enter">
          {analysis.heard && (
            <p className="muted row" style={{ gap: 6 }}><Headphones size={16} /> {t("add.heard")} <b>{analysis.heard}</b></p>
          )}
          {analysis.suggestions.length > 0 && (
            <div className="stack-sm">
              <p>{t("add.didYouMean")}</p>
              <div className="chips">
                {analysis.suggestions.map((s) => (
                  <button key={s} className="chip" onClick={() => { setText(s); submit(s); }}>
                    <Sparkles size={14} /> {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {analysis.issues.map((i) => <p key={i} className="hint">• {i}</p>)}

          {analysis.senses.length === 0 ? (
            <p>{t("add.notFound")}</p>
          ) : (
            <>
              <div>
                <h2>{analysis.display} {analysis.reading && <span className="muted">[{analysis.reading}]</span>}</h2>
                {analysis.pos && <span className="pill" style={{ marginTop: 6 }}>{analysis.pos}</span>}
              </div>
              <p className="hint">{analysis.senses.length > 1 ? t("add.pickMany") : t("add.pickOne")}</p>
              <div className="stack-sm stagger">
                {analysis.senses.map((s, i) => (
                  <div key={i} className={chosen.includes(i) ? "sense chosen" : "sense"} onClick={() => toggle(i)} role="checkbox" aria-checked={chosen.includes(i)}>
                    <span className="check"><Check size={14} strokeWidth={3} /></span>
                    <div>
                      <b>{s.translation}</b> {s.note && <span className="muted">({s.note})</span>}
                      {s.example && <div className="example">{s.example}<br /><span className="muted">{s.example_translation}</span></div>}
                    </div>
                  </div>
                ))}
              </div>
              {analysis.notes && <div className="notice info"><Lightbulb size={16} /><span>{analysis.notes}</span></div>}
              {analysis.duplicates.length > 0 && (
                <div className="notice warn">
                  <AlertTriangle size={16} />
                  <span>{t("add.duplicate", { t: analysis.duplicates.flatMap((d) => d.translations).join("; ") })}</span>
                </div>
              )}
              <button className="primary wide" onClick={save} disabled={busy || !chosen.length}>
                <Check size={18} /> {t("add.save")}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
