import { Fragment, useCallback, useState } from "react";
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, Headphones, Lightbulb, MessageCircleQuestion, Mic, Pencil, Plus,
  RotateCcw, Sparkles, Square, X,
} from "lucide-react";
import { api, type Analysis, type Answer, type Me } from "../api";
import { haptic, tg } from "../telegram";
import { useRecorder } from "../useRecorder";
import { Thinking } from "../ui";
import { t } from "../i18n";

interface Props { me: Me; onError: (e: unknown) => void; onSaved: () => void }

/** Rimy's text with **bold** words (the AI marks the words it teaches). */
function Rich({ text }: { text: string }) {
  return (
    <p style={{ whiteSpace: "pre-line" }}>
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <b key={i}>{part}</b> : <Fragment key={i}>{part}</Fragment>))}
    </p>
  );
}

/** Add a word by voice (the main way) or text: AI analysis → pick the meaning(s) → save.
 *  A question instead of a word gets Rimy's answer, like in the chat. */
export function AddScreen({ me, onError, onSaved }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [reply, setReply] = useState<Answer | null>(null);  // Rimy's answer to a question
  const [chosen, setChosen] = useState<number[]>([]);
  const [mine, setMine] = useState(false);  // "macchina - машина": the learner's translation is ticked
  const [own, setOwn] = useState<string | null>(null);  // typing their own translation instead of ours
  const [explanation, setExplanation] = useState("");
  const [explaining, setExplaining] = useState(false);
  const [saved, setSaved] = useState("");
  const [retry, setRetry] = useState(false);  // came back with "not that word"
  const [added, setAdded] = useState<string[]>([]);  // words from the current answer already saved
  const [opened, setOpened] = useState("");  // the answer's word whose card is open

  // the app scrolls inside .screen: results open at its top
  const toTop = () => document.querySelector<HTMLElement>(".screen")?.scrollTo({ top: 0, behavior: "smooth" });

  const reset = () => {
    setAnalysis(null);
    setReply(null);
    setOwn(null);
    setExplanation("");
  };

  /** keepAnswer: a word opened from Rimy's answer; the answer stays, to come back and add more words. */
  const show = (result: Analysis | Answer, keepAnswer = false) => {
    if (keepAnswer) {
      setOwn(null);
      setExplanation("");
    } else {
      reset();
      setAdded([]);
    }
    setSaved("");
    setRetry(false);
    if (result.kind === "answer") {
      setReply(result);
    } else {
      setAnalysis(result);
      setMine(Boolean(result.user_translation));
      // their own translation goes first and alone; ours stay below to pick from if they want
      setChosen(result.user_translation || !result.senses.length ? [] : [0]);
    }
    haptic.tap();
    toTop();
  };

  const close = () => {
    haptic.tap();
    reset();
  };

  /** From a word card opened from an answer: back to the answer, nothing saved. */
  const backToAnswer = () => {
    haptic.tap();
    setAnalysis(null);
    setOwn(null);
    setExplanation("");
    toTop();
  };

  /** We understood a different word: back to the input with what we heard, to fix it or say it again. */
  const wrongWord = () => {
    haptic.tap();
    if (analysis) setText(analysis.heard || analysis.lemma || text);
    reset();
    setRetry(true);
    toTop();
  };

  const run = async (job: () => Promise<Analysis | Answer>, keepAnswer = false) => {
    setBusy(true);
    try {
      show(await job(), keepAnswer);
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
  // a word from Rimy's answer: with the meaning it had there, the answer stays underneath
  const openFromAnswer = (word: string, meaning: string) => {
    if (!reply) return;
    setOpened(word);
    run(() => api.analyze(word, meaning, reply.answer), true);
  };

  const explain = async () => {
    if (!analysis) return;
    haptic.tap();
    setExplaining(true);
    try {
      const first = analysis.user_translation || analysis.senses[chosen[0] ?? 0]?.translation || "";
      setExplanation((await api.explain(analysis.display, first)).text);
    } catch (e) {
      onError(e);
    } finally {
      setExplaining(false);
    }
  };

  const translations = (): string[] => {
    if (!analysis) return [];
    if (own !== null) return own.trim() ? [own.trim()] : [];
    return [...(mine ? [analysis.user_translation] : []), ...chosen.map((i) => analysis.senses[i].translation)];
  };

  const save = async () => {
    if (!analysis) return;
    const list = translations();
    if (!list.length) return;
    // the example comes from the first ticked meaning (or the first one): it shows the word in use
    const sense = analysis.senses[chosen[0] ?? 0];
    setBusy(true);
    try {
      const word = await api.saveWord({
        lemma: analysis.lemma,
        display: analysis.display,
        reading: analysis.reading,
        pos: analysis.pos,
        translations: list,
        example: sense?.example ?? "",
        example_translation: sense?.example_translation ?? "",
        notes: analysis.notes,
      });
      haptic.success();
      if (word.achievement) tg?.showAlert(t("toast.card"));  // a streak / vocabulary card was sent to the chat
      setSaved(word.display);
      if (reply) {  // back to the answer: the next word is one tap away
        setAdded((a) => [...a, analysis.lemma, analysis.display, opened]);
        setAnalysis(null);
        setOwn(null);
        setExplanation("");
      } else {
        reset();
        setText("");
      }
      toTop();
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

  // --- Rimy answers a question (a word card opened from it is shown on top of it, below) ---
  if (reply && !analysis) {
    return (
      <div className="stack">
        <div className="card result-card">
          <button className="icon result-close" onClick={close} aria-label={t("add.cancel")}><X size={20} /></button>
          <p className="muted row" style={{ gap: 6, paddingRight: 36 }}><MessageCircleQuestion size={16} /> {reply.question}</p>
          <span className="eyebrow">{me.mascot}</span>
          <Rich text={reply.answer} />
          {reply.answer_words.length > 0 && (
            <div className="stack-sm">
              <p className="hint">{t("add.answerWords")}</p>
              <div className="chips">
                {reply.answer_words.map((w) => {
                  const done = added.includes(w.word);
                  return (
                    <button
                      key={w.word}
                      className={done ? "chip done" : "chip"}
                      onClick={() => openFromAnswer(w.word, w.meaning)}
                      disabled={busy || done}
                    >
                      {done ? <Check size={14} /> : <Plus size={14} />} {w.word}
                      {done ? <span className="muted"> · {t("add.added")}</span> : w.meaning && <span className="muted"> · {w.meaning}</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {busy && <Thinking text={t("add.thinking", { mascot: me.mascot })} />}
        </div>
        {saved && (
          <div className="notice ok enter">
            <CheckCircle2 size={18} />
            <span>{t("add.savedShort", { word: saved })}</span>
          </div>
        )}
        <div className="add-actions">
          <button className="primary wide" onClick={close}><Mic size={18} /> {t("add.another")}</button>
        </div>
      </div>
    );
  }

  // --- the recognised word: drops in at the top, the actions stay at hand at the bottom ---
  if (analysis) {
    const found = analysis.senses.length > 0 || Boolean(analysis.user_translation);
    return (
      <div className="stack">
        <div className="card result-card">
          <button className="icon result-close" onClick={reply ? backToAnswer : close} aria-label={t("add.cancel")}><X size={20} /></button>
          {analysis.heard && (
            <p className="muted row" style={{ gap: 6, paddingRight: 36 }}><Headphones size={16} /> {t("add.heard")} <b>{analysis.heard}</b></p>
          )}
          {found ? (
            <div>
              <h2>{analysis.display} {analysis.reading && <span className="muted">[{analysis.reading}]</span>}</h2>
              {analysis.pos && <span className="pill" style={{ marginTop: 6 }}>{analysis.pos}</span>}
            </div>
          ) : (
            <p>{t("add.notFound")}</p>
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

          {found && own === null && (
            <>
              <p className="hint">{analysis.senses.length + (analysis.user_translation ? 1 : 0) > 1 ? t("add.pickMany") : t("add.pickOne")}</p>
              <div className="stack-sm stagger">
                {analysis.user_translation && (
                  <div className={mine ? "sense chosen" : "sense"} onClick={() => { haptic.tap(); setMine((m) => !m); }} role="checkbox" aria-checked={mine}>
                    <span className="check"><Check size={14} strokeWidth={3} /></span>
                    <div><b>{analysis.user_translation}</b> <span className="pill">{t("add.yours")}</span></div>
                  </div>
                )}
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
            </>
          )}
          {analysis.notes && <div className="notice info"><Lightbulb size={16} /><span>{analysis.notes}</span></div>}
          {analysis.duplicates.length > 0 && (
            <div className="notice warn">
              <AlertTriangle size={16} />
              <span>{t("add.duplicate", { t: analysis.duplicates.flatMap((d) => d.translations).join("; ") })}</span>
            </div>
          )}

          {found && (explanation ? (
            <div className="explain enter"><span className="eyebrow">{me.mascot}</span><Rich text={explanation} /></div>
          ) : explaining ? (
            <Thinking text={t("add.explaining", { mascot: me.mascot })} />
          ) : (
            <button className="ghost explain-btn" onClick={explain}><MessageCircleQuestion size={16} /> {t("add.explain")}</button>
          ))}
        </div>

        <div className="add-actions">
          {own !== null && (
            <div className="input-row enter">
              <input
                autoFocus
                value={own}
                onChange={(e) => setOwn(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && own.trim() && save()}
                placeholder={t("add.ownPlaceholder")}
                maxLength={120}
              />
            </div>
          )}
          {found && (
            <button className="primary wide" onClick={save} disabled={busy || !translations().length}>
              <Check size={18} /> {own !== null ? t("add.ownSave") : t("add.save")}
            </button>
          )}
          <div className="row">
            {found && own === null && (
              <button onClick={() => { haptic.tap(); setOwn(""); }}><Pencil size={16} /> {t("add.own")}</button>
            )}
            {own !== null && <button onClick={() => { haptic.tap(); setOwn(null); }}><X size={16} /> {t("add.cancel")}</button>}
            {reply ? (
              <button onClick={backToAnswer}><ArrowLeft size={16} /> {t("add.backToAnswer")}</button>
            ) : (
              <button onClick={wrongWord}><RotateCcw size={16} /> {t("add.wrongWord")}</button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // --- the mic and the input ---
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
          autoFocus={retry}
        />
        <button className="primary square" onClick={() => submit()} disabled={busy || !text.trim()} aria-label={t("add.analyze")}>
          <ArrowRight size={20} />
        </button>
      </div>
      {busy && <Thinking text={t("add.thinking", { mascot: me.mascot })} />}
      {retry && <p className="hint center-text enter">{t("add.wrongHint")}</p>}
      <p className="hint center-text">{t("add.tip")}</p>
      {!me.premium && wordsLeft !== null && wordsLeft !== undefined && (
        <p className="hint center-text">{t("add.voiceLeft", { n: wordsLeft })}</p>
      )}

      {saved && (
        <div className="notice ok enter">
          <CheckCircle2 size={18} />
          <span>{t("add.saved", { word: saved })}</span>
        </div>
      )}
    </div>
  );
}
