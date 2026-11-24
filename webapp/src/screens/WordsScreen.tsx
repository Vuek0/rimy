import { useEffect, useMemo, useState } from "react";
import { BookOpen, Search, Trash2, Volume2 } from "lucide-react";
import { api, speak, type Word } from "../api";
import { haptic } from "../telegram";
import { FullLoader } from "../ui";

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
      haptic.tap();
      setWords((ws) => ws?.filter((w) => w.id !== word.id) ?? null);
      setTotal((t) => t - 1);
      onChange();
    } catch (e) {
      onError(e);
    }
  };

  if (!words) return <FullLoader text="Загружаю слова…" />;

  return (
    <div className="stack">
      <div className="spread enter">
        <h1>Мои слова</h1>
        <span className="pill">{total}</span>
      </div>
      <div className="search enter">
        <Search size={18} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск по словам и переводам" />
      </div>
      {shown.length === 0 && (
        <div className="center" style={{ minHeight: "40vh" }}>
          <div className="celebrate"><BookOpen size={40} /></div>
          <p className="muted">{words.length ? "Ничего не нашлось" : "Пока пусто. Добавь первое слово голосом!"}</p>
        </div>
      )}
      <div className="stack-sm stagger">
        {shown.map((w) => (
          <div key={w.id} className="card word-row">
            <div>
              <b>{w.display}</b> {w.reading && <span className="muted">[{w.reading}]</span>}
              <div className="muted">{w.translations.join("; ")}</div>
            </div>
            <div className="row">
              <button className="icon" onClick={() => speak(w.id).catch(onError)} aria-label="Озвучить"><Volume2 size={20} /></button>
              <button className="icon" onClick={() => remove(w)} aria-label="Удалить"><Trash2 size={19} /></button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
