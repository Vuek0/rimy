import { useState } from "react";
import { Check, Crown, Gift, Loader2 } from "lucide-react";
import { api, type Me } from "../api";
import { haptic, tg } from "../telegram";
import { PromoForm } from "../ui";
import { t } from "../i18n";

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
          <li><Check size={18} /> {t("pay.perk1")}</li>
          <li><Check size={18} /> {t("pay.perk2")}</li>
          <li><Check size={18} /> {t("pay.perk3", { mascot: me.mascot })}</li>
          <li><Check size={18} /> {t("pay.perk4")}</li>
        </ul>
        {me.promo_pending_days > 0 && (
          <div className="notice ok"><Gift size={16} /><span>{t("pay.promoAdds", { n: me.promo_pending_days })}</span></div>
        )}
        <button className="primary wide" onClick={buy} disabled={busy}>
          {busy ? <Loader2 size={18} className="spin" /> : <Crown size={18} />}
          {t("pay.subscribe", { n: me.price_stars })}
        </button>
        {promoOpen ? (
          <div className="enter"><PromoForm onDone={onPaid} compact /></div>
        ) : (
          <button className="ghost wide" onClick={() => setPromoOpen(true)}><Gift size={18} /> {t("pay.havePromo")}</button>
        )}
        <button className="ghost wide" onClick={onClose} style={{ color: "var(--muted)" }}>{t("pay.notNow")}</button>
        <p className="hint center-text">{t("pay.reviewFree")}</p>
      </div>
    </div>
  );
}
