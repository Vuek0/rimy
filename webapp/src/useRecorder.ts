import { useCallback, useRef, useState } from "react";

const MAX_SECONDS = 30;
// Android/desktop WebViews record webm/opus, iOS records mp4/aac: both are accepted by Whisper.
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** Tap to start, tap to stop: returns the recorded clip to `onDone`. */
export function useRecorder(onDone: (blob: Blob) => void) {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number>();

  const stop = useCallback(() => {
    window.clearTimeout(timer.current);
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  const start = useCallback(async () => {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Запись голоса здесь не поддерживается - отправь голосовое боту в чат 🎙");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t));
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        if (blob.size > 0) onDone(blob);
      };
      recorder.current = rec;
      rec.start();
      setRecording(true);
      timer.current = window.setTimeout(stop, MAX_SECONDS * 1000);
    } catch {
      setError("Нет доступа к микрофону. Разреши его в настройках Telegram или отправь голосовое в чат.");
    }
  }, [onDone, stop]);

  const toggle = useCallback(() => (recording ? stop() : start()), [recording, start, stop]);
  return { recording, error, toggle };
}
