import { initData } from "./telegram";

export interface Quota { kind: string; used: number; limit: number; left: number | null }
export interface Me {
  id: number;
  first_name: string;
  native_lang: string;
  lang: string;
  langs: { code: string; name: string; flag: string }[];
  base_langs: { code: string; name: string }[];
  premium: boolean;
  premium_until: string | null;
  price_stars: number;
  quotas: Record<string, Quota>;
  stats: { words: number; due: number; reviewed_today: number; streak: number };
  mascot: string;
  is_admin: boolean;
  promo_pending_days: number;
}
export interface Promo {
  id: number; code: string; days: number; max_uses: number; active: boolean;
  used: number; applied: number; created_at: string;
}
export interface Point { day: string; value: number }
export interface Dashboard {
  generated_at: string;
  today: string;
  days: number;
  totals: {
    users: number; new_today: number; active_today: number; words: number;
    reviews: number; premium: number; payments: number; stars: number;
  };
  series: { new_users: Point[]; active_users: Point[]; words: Point[]; reviews: Point[]; ai: Point[] };
  funnel: { key: string; label: string; users: number }[];
  ai_today: { kind: string; label: string; count: number }[];
  refs: { ref: string; users: number }[];
}
export interface Person {
  id: number; first_name: string; username: string; native_lang: string; premium: boolean;
  words: number; ref: string; created_at: string; last_active_at: string | null;
}
interface LangTag { code: string; name: string; flag: string }
export interface PersonProfile {
  id: number; first_name: string; username: string; ref: string;
  native_lang: LangTag; decks: (LangTag & { words: number })[];
  premium: boolean; premium_until: string | null; onboarded: boolean; reminders: boolean;
  practice_mode: boolean; timezone: string; created_at: string; last_active_at: string | null;
  stats: { words: number; reviews: number; last_review_at: string | null; due: number };
  ai_total: Record<string, number>;
  payments: { stars: number; at: string }[];
  promos: { code: string; days: number; at: string; applied: boolean }[];
  funnel: { key: string; label: string; at: string | null }[];
  recent_words: { display: string; translation: string; at: string }[];
}
export interface Sense { translation: string; example: string; example_translation: string; note: string }
export interface Word {
  id: number; lemma: string; display: string; reading: string; pos: string;
  translations: string[]; example: string; example_translation: string; notes: string; created_at: string;
}
export interface Analysis {
  heard?: string; is_valid: boolean; lemma: string; display: string; reading: string; pos: string;
  senses: Sense[]; suggestions: string[]; notes: string; issues: string[]; duplicates: Word[];
}
export interface Card {
  id: number; direction: "fwd" | "rev"; prompt: string; prompt_lang: string; question: string;
  word: Word; intervals: Record<string, string>;
}
export interface Check { verdict: "correct" | "almost" | "wrong" | "not_answer" | "unknown"; rating: number | null; comment: string; answer: string }
export type Draft = Omit<Word, "id" | "created_at">;

/** The free plan's daily limit is used up (HTTP 402): the UI shows the paywall. */
export class LimitError extends Error {
  constructor(message: string, public kind: string) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `tma ${initData()}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (res.ok) return res.json() as Promise<T>;
  const body = await res.json().catch(() => ({}));
  const detail = body?.detail;
  if (res.status === 402 && detail?.code === "limit") throw new LimitError(detail.message, detail.kind);
  throw new Error(typeof detail === "string" ? detail : `Ошибка ${res.status}`);
}

const post = <T>(path: string, data?: unknown) =>
  request<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });

function audioForm(blob: Blob): FormData {
  const form = new FormData();
  const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("audio", blob, `voice.${ext}`);
  return form;
}

export const api = {
  me: () => request<Me>("/api/me"),
  setLang: (code: string) => post<{ lang: string }>("/api/lang", { code }),
  setBase: (code: string) => post<{ native_lang: string }>("/api/base", { code }),
  track: (name: string, props: Record<string, unknown> = {}) => post("/api/events", { name, props }).catch(() => {}),

  analyze: (text: string) => post<Analysis>("/api/words/analyze", { text }),
  analyzeVoice: (blob: Blob) => request<Analysis>("/api/words/analyze-voice", { method: "POST", body: audioForm(blob) }),
  saveWord: (draft: Draft) => post<Word>("/api/words", draft),
  words: () => request<{ words: Word[]; total: number }>("/api/words"),
  deleteWord: (id: number) => request(`/api/words/${id}`, { method: "DELETE" }),

  nextCard: (after?: number) =>
    request<{ card: Card | null; due: number; next_in?: string | null }>(`/api/review/next${after ? `?after=${after}` : ""}`),
  answer: (cardId: number, text: string) => post<Check>(`/api/review/${cardId}/answer`, { text }),
  answerVoice: (cardId: number, blob: Blob) =>
    request<Check>(`/api/review/${cardId}/answer-voice`, { method: "POST", body: audioForm(blob) }),
  rate: (cardId: number, rating: number) => post<{ next_in: string }>(`/api/review/${cardId}/rate`, { rating }),

  invoice: () => post<{ link: string }>("/api/premium/invoice"),

  redeemPromo: (code: string) => post<{ status: string; ok: boolean; message: string; days: number }>("/api/promo", { code }),

  dashboard: (days: number) => request<Dashboard>(`/api/admin/dashboard?days=${days}`),
  promos: () => request<{ promos: Promo[] }>("/api/admin/promos"),
  createPromo: (days: number, maxUses: number, code = "") =>
    post<{ code: string; id: number }>("/api/admin/promos", { days, max_uses: maxUses, code }),
  setPromoActive: (id: number, active: boolean) => post(`/api/admin/promos/${id}`, { active }),
  people: (q: string, offset = 0) =>
    request<{ total: number; users: Person[] }>(`/api/admin/users?q=${encodeURIComponent(q)}&offset=${offset}`),
  person: (id: number) => request<PersonProfile>(`/api/admin/users/${id}`),
};

/** A Telegram profile photo as an object URL, or null if there is none / it's hidden.
 *  No id: the current user's own; with an id: anyone's (admins only). */
export async function avatarUrl(userId?: number): Promise<string | null> {
  const path = userId === undefined ? "/api/avatar" : `/api/admin/users/${userId}/avatar`;
  const res = await fetch(path, { headers: { Authorization: `tma ${initData()}` } });
  return res.ok ? URL.createObjectURL(await res.blob()) : null;
}

/** Play a word's (or its example's) pronunciation. */
export async function speak(wordId: number, part: "word" | "example" = "word"): Promise<void> {
  const res = await fetch(`/api/tts/${wordId}?part=${part}`, { headers: { Authorization: `tma ${initData()}` } });
  if (!res.ok) throw new Error("Озвучка недоступна");
  const url = URL.createObjectURL(await res.blob());
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  await audio.play();
}
