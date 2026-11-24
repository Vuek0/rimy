import { useState } from "react";
import { Gift, Loader2 } from "lucide-react";
import { api } from "./api";
import { haptic } from "./telegram";
import { t } from "./i18n";

/** "Rimy is thinking" with three bouncing dots. */
export function Thinking({ text }: { text: string }) {
  return (
    <p className="loader center-text" style={{ justifyContent: "center" }}>
      {text}
      <span className="dots"><span /><span /><span /></span>
    </p>
  );
}

export function FullLoader({ text }: { text: string }) {
  return (
    <div className="center">
      <Loader2 size={28} className="spin muted" />
      <p className="muted">{text}</p>
    </div>
  );
}

/** Promo code field: the result (applied / waits for the payment / error) is shown under it. */
export function PromoForm({ onDone, compact = false }: { onDone: () => void; compact?: boolean }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const submit = async () => {
    if (!code.trim()) return;
    setBusy(true);
    try {
      const res = await api.redeemPromo(code.trim());
      setResult(res);
      if (res.ok) {
        haptic.success();
        setCode("");
        onDone();
      } else {
        haptic.error();
      }
    } catch (e) {
      setResult({ ok: false, message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack-sm">
      {!compact && (
        <div className="row" style={{ gap: 10 }}>
          <div className="stat-icon" style={{ margin: 0 }}><Gift size={18} /></div>
          <div>
            <h3>{t("promo.title")}</h3>
            <p className="hint">{t("promo.hint")}</p>
          </div>
        </div>
      )}
      <div className="input-row">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="RIMY-XXXXXX"
          maxLength={40}
          disabled={busy}
          className="code"
          autoCapitalize="characters"
        />
        <button className="primary" onClick={submit} disabled={busy || !code.trim()}>
          {busy ? <Loader2 size={18} className="spin" /> : t("promo.apply")}
        </button>
      </div>
      {result && (
        <div className={`notice enter ${result.ok ? "ok" : "danger"}`}>
          <Gift size={16} />
          <span style={{ whiteSpace: "pre-line" }}>{result.message.replace(/^\S*🎁\s*/u, "")}</span>
        </div>
      )}
    </div>
  );
}
