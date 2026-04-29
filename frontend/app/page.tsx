"use client";

import { useEffect, useRef, useState } from "react";

type Mode = "image" | "video";

type Job = {
  id: string;
  mode: string;
  prompt: string;
  status: "queued" | "running" | "done" | "error";
  outputs: { url: string; filename: string }[];
  error: string | null;
  created_at: number;
};

const IMAGE_RATIOS: Record<string, [number, number]> = {
  "1:1": [1024, 1024],
  "16:9": [1280, 720],
  "9:16": [720, 1280],
  "4:3": [1152, 896],
  "3:4": [896, 1152],
};

const VIDEO_RATIOS: Record<string, [number, number]> = {
  "16:9": [1024, 576],
  "1:1": [768, 768],
  "9:16": [576, 1024],
};

const VIDEO_LENGTHS: Record<string, number> = {
  "3s": 73,
  "4s": 97,
  "5s": 121,
};

export default function Home() {
  const [mode, setMode] = useState<Mode>("image");
  const [prompt, setPrompt] = useState("");
  const [ratio, setRatio] = useState("1:1");
  const [duration, setDuration] = useState("4s");
  const [enhance, setEnhance] = useState(true);
  const [imageModels, setImageModels] = useState<{ id: string; label: string; notes: string }[]>([]);
  const [imageModel, setImageModel] = useState<string>("flux-schnell");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [open, setOpen] = useState<Job | null>(null);
  const pollers = useRef<Map<string, AbortController>>(new Map());

  // Esc to close lightbox
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Reset ratio when mode changes
  useEffect(() => {
    setRatio(mode === "image" ? "1:1" : "16:9");
  }, [mode]);

  // Load available image models on mount
  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: { image: typeof imageModels; default_image: string }) => {
        setImageModels(data.image);
        setImageModel(data.default_image);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Initial job list
  useEffect(() => {
    fetch("/api/jobs?limit=24")
      .then((r) => r.json())
      .then((data: Job[]) => {
        setJobs(data);
        for (const j of data) {
          if (j.status === "queued" || j.status === "running") attachStream(j.id);
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Background sweep — every 5s re-fetch the whole list. Catches any
  // updates that an individual poller may have missed.
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const r = await fetch("/api/jobs?limit=24", { cache: "no-store" });
        const data = (await r.json()) as Job[];
        setJobs(data);
      } catch {
        /* network blip — try again next tick */
      }
    }, 5000);
    return () => clearInterval(t);
  }, []);

  // Per-job poller. Plain HTTP polling — robust across tunnels, proxies,
  // and connection drops. Stops when the job is terminal.
  function attachStream(jobId: string) {
    if (pollers.current.has(jobId)) return;
    const ac = new AbortController();
    pollers.current.set(jobId, ac);

    (async () => {
      const start = Date.now();
      while (!ac.signal.aborted && Date.now() - start < 15 * 60 * 1000) {
        try {
          const r = await fetch(`/api/jobs/${jobId}`, { signal: ac.signal, cache: "no-store" });
          if (!r.ok) throw new Error(String(r.status));
          const data = (await r.json()) as Job;
          setJobs((prev) =>
            prev.map((j) =>
              j.id === jobId
                ? { ...j, status: data.status, outputs: data.outputs, error: data.error }
                : j,
            ),
          );
          if (data.status === "done" || data.status === "error") break;
        } catch {
          /* ignore — next iteration retries */
        }
        await new Promise((res) => setTimeout(res, 2000));
      }
      pollers.current.delete(jobId);
    })();
  }

  async function onSubmit() {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const [w, h] = mode === "image" ? IMAGE_RATIOS[ratio] : VIDEO_RATIOS[ratio];
      const body: Record<string, unknown> = {
        prompt: prompt.trim(),
        mode,
        width: w,
        height: h,
        enhance,
      };
      if (mode === "image") body.model = imageModel;
      if (mode === "video") body.length = VIDEO_LENGTHS[duration];
      const r = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.text();
        throw new Error(err || `request failed: ${r.status}`);
      }
      const { id } = (await r.json()) as { id: string };
      const placeholder: Job = {
        id,
        mode,
        prompt: prompt.trim(),
        status: "queued",
        outputs: [],
        error: null,
        created_at: Date.now() / 1000,
      };
      setJobs((prev) => [placeholder, ...prev]);
      setPrompt("");
      attachStream(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app">
      <header className="hero">
        <h1>softstudio</h1>
        <p>local image and video generation, your machine, your rules</p>
      </header>

      <section className="composer">
        <div className="mode-tabs">
          <button
            className={`ghost ${mode === "image" ? "active" : ""}`}
            onClick={() => setMode("image")}
          >
            Image
          </button>
          <button
            className={`ghost ${mode === "video" ? "active" : ""}`}
            onClick={() => setMode("video")}
          >
            Video
          </button>
        </div>

        <textarea
          rows={3}
          placeholder={mode === "image" ? "a cinematic photo of..." : "a slow-motion shot of..."}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit();
          }}
        />

        <div className="controls">
          {mode === "image" && imageModels.length > 0 && (
            <label>
              model
              <select value={imageModel} onChange={(e) => setImageModel(e.target.value)}>
                {imageModels.map((m) => (
                  <option key={m.id} value={m.id} title={m.notes}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            ratio
            <select value={ratio} onChange={(e) => setRatio(e.target.value)}>
              {Object.keys(mode === "image" ? IMAGE_RATIOS : VIDEO_RATIOS).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </label>
          {mode === "video" && (
            <label>
              length
              <select value={duration} onChange={(e) => setDuration(e.target.value)}>
                {Object.keys(VIDEO_LENGTHS).map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            className={`ghost ${enhance ? "active" : ""}`}
            onClick={() => setEnhance((v) => !v)}
            title="Auto-expand short prompts into a cinematic description (recommended)"
          >
            ✨ enhance prompt {enhance ? "on" : "off"}
          </button>
        </div>

        {error && <div className="error-banner">{error}</div>}

        <div className="submit-row">
          <span style={{ color: "var(--text-dim)", fontSize: 13 }}>⌘/Ctrl-Enter to submit</span>
          <button className="primary" onClick={onSubmit} disabled={busy || !prompt.trim()}>
            {busy ? "submitting…" : mode === "image" ? "Generate image" : "Generate video"}
          </button>
        </div>
      </section>

      <section className="gallery">
        {jobs.length === 0 && (
          <div style={{ gridColumn: "1 / -1", textAlign: "center", color: "var(--text-dim)", padding: 60 }}>
            no generations yet — type a prompt above to get started
          </div>
        )}
        {jobs.map((job) => {
          const ready = job.status === "done" && job.outputs[0];
          return (
            <div
              key={job.id}
              className={`tile ${ready ? "" : "no-click"}`}
              onClick={() => ready && setOpen(job)}
              role={ready ? "button" : undefined}
              tabIndex={ready ? 0 : undefined}
              onKeyDown={(e) => {
                if (ready && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  setOpen(job);
                }
              }}
            >
              {ready ? (
                <img src={job.outputs[0].url} alt={job.prompt} />
              ) : job.status === "error" ? (
                <div className="pending" style={{ color: "var(--error)" }}>
                  <span>failed</span>
                  <span style={{ fontSize: 11, padding: "0 12px", textAlign: "center" }}>
                    {(job.error || "").slice(0, 120)}
                  </span>
                </div>
              ) : (
                <div className="pending">
                  <div className="spinner" />
                  <span>{job.status === "queued" ? "queued" : "rendering"}</span>
                </div>
              )}
              <div className="meta">{job.prompt.slice(0, 80)}</div>
            </div>
          );
        })}
      </section>

      {open && open.outputs[0] && (
        <div className="lightbox" onClick={() => setOpen(null)}>
          <a
            className="open-original"
            href={open.outputs[0].url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            open original ↗
          </a>
          <button className="close" onClick={() => setOpen(null)} aria-label="close">
            ×
          </button>
          <div className="stage" onClick={(e) => e.stopPropagation()}>
            <img src={open.outputs[0].url} alt={open.prompt} />
          </div>
          <div className="caption">
            <strong>{open.prompt}</strong>
          </div>
        </div>
      )}
    </main>
  );
}
