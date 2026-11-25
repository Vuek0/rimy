import { BookOpen, CalendarCheck, Crown, Flame, Gift, Globe2, Languages, Layers, Send, Share2, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api, avatarUrl, type Me, type Share } from "../api";
import { haptic, tg } from "../telegram";
import { PromoForm } from "../ui";
import { formatDate, t } from "../i18n";

interface Props { me: Me; onError: (e: unknown) => void; onChange: () => void; onPremium: () => void }

/** Share the progress card: Telegram's chat picker (or the card lands in the bot chat to forward), or a story. */
function ShareCard({ me, onError }: { me: Me; onError: (e: unknown) => void }) {
  const [info, setInfo] = useState<Share | null>(null);
  const [busy, setBusy] = useState(false);
  const hasWords = me.stats.words > 0;
  useEffect(() => {
    if (hasWords) api.share().then(setInfo).catch(() => undefined);
  }, [hasWords, me.stats.streak, me.stats.words]);

  const toChat = async () => {
    haptic.tap();
    if (info?.prepared_id && tg?.shareMessage) {
      tg.shareMessage(info.prepared_id, (sent) => {
        if (sent) { haptic.success(); api.track("shared", { via: "chat", kind: info.kind }); }
      });
      return;
    }
    setBusy(true);
    try {
      await api.shareSend();
      haptic.success();
      tg?.showAlert(t("share.sent"));
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  const toStory = () => {
    if (!info?.story_url || !tg?.shareToStory) return;
    haptic.tap();
    tg.shareToStory(info.story_url, { text: `${info.text} ${info.link}` });
    api.track("shared", { via: "story", kind: info.kind });
  };

  return (
    <div className="card share-card">
      <div className="row" style={{ gap: 10 }}>
        <span className="stat-icon" style={{ margin: 0 }}><Share2 size={18} /></span>
        <div>
          <h3>{t("share.title")}</h3>
          <p className="hint">{hasWords ? t("share.hint") : t("share.empty")}</p>
        </div>
      </div>
      {info?.image_url && <img className="share-preview" src={info.image_url} alt="" />}
      {hasWords && (
        <div className="row">
          <button className="primary" onClick={toChat} disabled={busy}><Send size={18} /> {t("share.chat")}</button>
          {info?.story_url && tg?.shareToStory && (
            <button onClick={toStory}><Sparkles size={18} /> {t("share.story")}</button>
          )}
        </div>
      )}
      <p className="hint">{t("share.lazy")}</p>
    </div>
  );
}


export function ProfileScreen({ me, onError, onChange, onPremium }: Props) {
  const [photo, setPhoto] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    avatarUrl().then((u) => { url = u; setPhoto(u); }).catch(() => undefined);  // no photo: keep the initial
    return () => { if (url) URL.revokeObjectURL(url); };
  }, []);

  const change = (job: () => Promise<unknown>) => async () => {
    haptic.tap();
    try {
      await job();
      onChange();
    } catch (e) {
      onError(e);
    }
  };
  const until = me.premium_until ? formatDate(me.premium_until) : "";

  return (
    <div className="stack stagger">
      <div className="profile-head">
        <div className="avatar">
          {photo ? <img src={photo} alt="" /> : (me.first_name || "R").slice(0, 1).toUpperCase()}
        </div>
        <div>
          <h1>{me.first_name || t("prof.hello")}</h1>
          <p className="muted">{me.premium ? t("prof.premiumUntil", { d: until }) : t("prof.free")}</p>
        </div>
      </div>

      <div className="stats">
        <div className="stat"><span className="stat-icon"><BookOpen size={18} /></span><b>{me.stats.words}</b><span>{t("prof.words")}</span></div>
        <div className="stat"><span className="stat-icon"><Layers size={18} /></span><b>{me.stats.due}</b><span>{t("prof.due")}</span></div>
        <div className="stat"><span className="stat-icon"><CalendarCheck size={18} /></span><b>{me.stats.reviewed_today}</b><span>{t("prof.today")}</span></div>
        <div className="stat"><span className="stat-icon"><Flame size={18} /></span><b>{me.stats.streak}</b><span>{t("prof.streak")}</span></div>
      </div>

      <ShareCard me={me} onError={onError} />

      {me.premium ? (
        <div className="card premium-card">
          <div className="row"><Crown size={22} /><h2>{t("prof.premiumActive")}</h2></div>
          <p className="muted">{t("prof.premiumThanks", { d: until })}</p>
        </div>
      ) : (
        <div className="card">
          <h3>{t("prof.todayFree")}</h3>
          {Object.values(me.quotas).map((q) => (
            <div key={q.kind} className="quota">
              <span>{t(`quota.${q.kind}` as Parameters<typeof t>[0])}</span>
              <span className="muted">{q.used} / {q.limit}</span>
              <div className="bar"><div style={{ width: `${Math.min(100, (q.used / Math.max(1, q.limit)) * 100)}%` }} /></div>
            </div>
          ))}
          <button className="primary wide" onClick={onPremium}><Crown size={18} /> {t("prof.goPremium")}</button>
        </div>
      )}

      <div className="card">
        {me.promo_pending_days > 0 && (
          <div className="notice ok">
            <Gift size={16} />
            <span>{t("prof.promoWaiting", { n: me.promo_pending_days })}</span>
          </div>
        )}
        <PromoForm onDone={onChange} />
      </div>

      <div className="card">
        <div className="row" style={{ gap: 10 }}>
          <span className="stat-icon" style={{ margin: 0 }}><Languages size={18} /></span>
          <h3>{t("prof.learning")}</h3>
        </div>
        <div className="chips">
          {me.langs.map((l) => (
            <button key={l.code} className={l.code === me.lang ? "chip active" : "chip"} onClick={change(() => api.setLang(l.code))}>
              {l.flag} {l.name}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ gap: 10 }}>
          <span className="stat-icon" style={{ margin: 0 }}><Globe2 size={18} /></span>
          <div>
            <h3>{t("prof.base")}</h3>
            <p className="hint">{t("prof.baseHint", { mascot: me.mascot })}</p>
          </div>
        </div>
        <div className="chips">
          {me.base_langs.map((l) => (
            <button key={l.code} className={l.code === me.native_lang ? "chip active" : "chip"} onClick={change(() => api.setBase(l.code))}>
              {l.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
