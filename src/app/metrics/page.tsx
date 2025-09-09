"use client";
import { useEffect, useState } from "react";
const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

type Metrics = { count: number; accuracy: number | null; brier: number | null };

export default function MetricsPage() {
  const [data, setData] = useState<Metrics | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/metrics`);
        const j = await r.json();
        setData(j);
      } catch (e:any) { setErr(e?.message ?? "Hata"); }
    })();
  }, []);

  return (
    <main className="min-h-screen p-6 max-w-xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Metrikler</h1>
      {err && <div className="p-3 bg-red-100 text-red-800 rounded mb-4">{err}</div>}
      {data && (
        <div className="grid gap-3">
          <div className="p-4 rounded border">
            <div className="text-sm opacity-60">Tahmin-Sonuç Eşleşme Sayısı</div>
            <div className="text-2xl font-semibold">{data.count}</div>
          </div>
          <div className="p-4 rounded border">
            <div className="text-sm opacity-60">Accuracy</div>
            <div className="text-2xl font-semibold">{data.accuracy === null ? "-" : data.accuracy.toFixed(3)}</div>
          </div>
          <div className="p-4 rounded border">
            <div className="text-sm opacity-60">Brier</div>
            <div className="text-2xl font-semibold">{data.brier === null ? "-" : data.brier.toFixed(3)}</div>
          </div>
        </div>
      )}
    </main>
  );
}
