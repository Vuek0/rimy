import { useState } from "react";
import { Check, Crown, Gift, Loader2 } from "lucide-react";
import { api, type Me } from "../api";
import { haptic, tg } from "../telegram";
import { PromoForm } from "../ui";

interface Props { me: Me; reason: string; onClose: () => void; onPaid: () => void }

/** Premium offer; the payment itself is Telegram's native Stars invoice (openInvoice). */
export function Paywall({ me, reason, onClose, onPaid }: Props) {
  const [busy, setBusy] = useState(false);
  const [promoOpen, setPromoOpen] = useState(false);

  const buy = async () => {
    setBusy(true);
    try {
      const { link } = await api.invoice();
      if (!tg) {
        window.open(link, "_blank");
        return;
      }
      tg.openInvoice(link, (status) => {
        if (status === "paid") {
          haptic.success();
          api.track("purchase_client");
          onPaid();
          onClose();
        }
      });
    } catch (e) {
      tg?.showAlert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="grabber" />
        <div className="sheet-head">
          <div className="crown"><Crown size={32} /></div>
          <h2>Rimy Premium</h2>
          {reason && <p className="muted">{reason.split("\n")[0]}</p>}
        </div>
        <ul className="perks stagger">
          <li><Check size={18} /> Без лимита на AI-слова и голосовые</li>
          <li><Check size={18} /> Безлимитная AI-проверка ответов</li>
          <li><Check size={18} /> Разговорная практика с {me.mascot}</li>
          <li><Check size={18} /> Все языки сразу</li>
        </ul>
        {me.promo_pending_days > 0 && (
          <div className="notice ok"><Gift size={16} /><span>Твой промокод добавит ещё +{me.promo_pending_days} дн.</span></div>
        )}
        <button className="primary wide" onClick={buy} disabled={busy}>
          {busy ? <Loader2 size={18} className="spin" /> : <Crown size={18} />}
          Подписаться за {me.price_stars} Stars в месяц
        </button>
        {promoOpen ? (
          <div className="enter"><PromoForm onDone={onPaid} compact /></div>
        ) : (
          <button className="ghost wide" onClick={() => setPromoOpen(true)}><Gift size={18} /> У меня есть промокод</button>
        )}
        <button className="ghost wide" onClick={onClose} style={{ color: "var(--muted)" }}>Не сейчас</button>
        <p className="hint center-text">Повторение карточек всегда бесплатно</p>
      </div>
    </div>
  );
}
