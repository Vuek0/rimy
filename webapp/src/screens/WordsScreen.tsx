import { useEffect, useMemo, useState } from "react";
import { api, speak, type Word } from "../api";

interface Props { onError: (e: unknown) => void; onChange: () => void }

export function WordsScreen({ onError, onChange }: Props) {
  const [words, setWords] = useState<Word[] | null>(null);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.words().then((r) => { setWords(r.words); setTotal(r.total); }).catch(onError);
  }, [onError]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!words || !q) return words ?? [];
    return words.filter((w) => w.display.toLowerCase().includes(q) || w.translations.some((t) => t.toLowerCase().includes(q)));
  }, [words, query]);

  const remove = async (word: Word) => {
    if (!confirm(`Удалить «${word.display}»?`)) return;
    try {
      await api.deleteWord(word.id);
      setWords((ws) => ws?.filter((w) => w.id !== word.id) ?? null);
      setTotal((t) => t - 1);
      onChange();
    } catch (e) {
      onError(e);
    }
  };

  if (!words) return <div className="center muted">Загружаю слова…</div>;

  return (
    <div className="stack">
      <h1>Мои слова <span className="muted">{total}</span></h1>
      <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск" />
      {shown.length === 0 && <p className="muted">{words.length ? "Ничего не нашлось" : "Пока пусто - добавь первое слово ✨"}</p>}
      {shown.map((w) => (
        <div key={w.id} className="card word-row">
          <div>
            <b>{w.display}</b> {w.reading && <span className="muted">[{w.reading}]</span>}
            <div className="muted">{w.translations.join("; ")}</div>
          </div>
          <div className="row">
            <button className="icon" onClick={() => speak(w.id).catch(onError)}>🔊</button>
            <button className="icon" onClick={() => remove(w)}>🗑</button>
          </div>
        </div>
      ))}
    </div>
  );
}
