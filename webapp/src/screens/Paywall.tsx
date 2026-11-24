import { useState } from "react";
import { api, type Me } from "../api";
import { haptic, tg } from "../telegram";

interface Props { me: Me; reason: string; onClose: () => void; onPaid: () => void }

/** Premium offer; the payment itself is Telegram's native Stars invoice (openInvoice). */
export function Paywall({ me, reason, onClose, onPaid }: Props) {
  const [busy, setBusy] = useState(false);

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
      <div className="sheet stack" onClick={(e) => e.stopPropagation()}>
        <div className="big-emoji">⭐</div>
        <h2>Premium</h2>
        {reason && <p className="muted">{reason.split("\n")[0]}</p>}
        <ul className="perks">
          <li>Без лимита на AI-слова и голосовые</li>
          <li>Безлимитная AI-проверка ответов</li>
          <li>Разговорная практика с {me.mascot}</li>
          <li>Все языки сразу</li>
        </ul>
        <button className="primary wide" onClick={buy} disabled={busy}>
          Подписаться за {me.price_stars} ⭐ в месяц
        </button>
        <button className="secondary wide" onClick={onClose}>Не сейчас</button>
        <p className="hint">Повторение карточек всегда бесплатно</p>
      </div>
    </div>
  );
}
