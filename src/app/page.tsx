"use client";
import { useState, useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

type UpcomingResp = {
  sport_key: string | null;
  count: number;
  saved: number;
  items?: { match_id: string; player_a: string; player_b: string; p_home: number }[];
  note?: string;
};

export default function Home() {
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<UpcomingResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runUpcoming = async () => {
    try {
      setLoading(true); setError(null);
      const r = await fetch(`${API}/predict/upcoming?regions=eu`, { method: "POST" });
      const j = await r.json();
      setResp(j);
    } catch (e:any) {
      setError(e?.message ?? "Hata");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { /* sayfa açılır açılmaz dene */ runUpcoming(); }, []);

  return (
    <main className="min-h-screen p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Tennis Prediction — Dashboard</h1>
      <div className="mb-4 flex gap-2">
        <button
          onClick={runUpcoming}
          className="px-4 py-2 rounded bg-black text-white disabled:opacity-50"
          disabled={loading}
        >
          {loading ? "Çalışıyor..." : "Toplu Tahmin (EU)"}
        </button>
      </div>

      {error && <div className="p-3 bg-red-100 text-red-800 rounded mb-4">{error}</div>}

      {resp && (
        <div className="space-y-3">
          <div className="p-3 rounded border">
            <div className="font-medium">sport_key: {resp.sport_key ?? "-"}</div>
            <div>count: {resp.count} — saved: {resp.saved}</div>
            {resp.note && <div className="text-sm opacity-70">note: {resp.note}</div>}
          </div>

          {(resp.items?.length ?? 0) > 0 && (
            <table className="w-full text-sm border">
              <thead>
                <tr className="bg-gray-50">
                  <th className="text-left p-2 border">match_id</th>
                  <th className="text-left p-2 border">player_a</th>
                  <th className="text-left p-2 border">player_b</th>
                  <th className="text-left p-2 border">p_home</th>
                </tr>
              </thead>
              <tbody>
                {resp!.items!.map((it) => (
                  <tr key={it.match_id}>
                    <td className="p-2 border">{it.match_id}</td>
                    <td className="p-2 border">{it.player_a}</td>
                    <td className="p-2 border">{it.player_b}</td>
                    <td className="p-2 border">{it.p_home.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </main>
  );
}
