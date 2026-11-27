import { useCallback, useEffect, useRef, useState } from "react";
import { captureMicrophone } from "./audio.js";

export function useMicrophone(active) {
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState(null);
  const [reduceMotion, setReduceMotion] = useState(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
  const canvas = useRef(null);
  const resources = useRef({ capture: null, controller: null, frame: 0, levels: [] });
  // AudioWorklet посылает кадры чаще React-отрисовки. Шкала рисуется в canvas.
  const reduced = useRef(reduceMotion);

  function paintSamples(samples) {
    if (reduced.current) return;
    const current = resources.current;
    let peak = 0;
    for (const sample of samples) peak = Math.max(peak, Math.abs(sample));
    current.levels.push(peak);
    if (current.levels.length > 120) current.levels.shift();
    if (!current.frame) {
      current.frame = requestAnimationFrame(() => {
        current.frame = 0;
        drawMeter(canvas.current, current.levels);
      });
    }
  }

  const stop = useCallback((discard = false, notify = true) => {
    const current = resources.current;
    const { capture, controller } = current;
    current.capture = current.controller = null;
    if (current.frame) cancelAnimationFrame(current.frame);
    current.frame = 0;
    current.levels = [];
    drawMeter(canvas.current, []);
    const recording = capture?.stop({ discard });
    controller?.abort();
    if (notify) setPhase("idle");
    return recording || null;
  }, []);

  useEffect(() => {
    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => {
      reduced.current = query.matches;
      setReduceMotion(query.matches);
    };
    const onPageHide = () => stop(true);
    query.addEventListener("change", handleChange);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      query.removeEventListener("change", handleChange);
      window.removeEventListener("pagehide", onPageHide);
      stop(true, false);
    };
  }, [stop]);

  useEffect(() => {
    if (!active) stop(true);
  }, [active, stop]);

  async function start() {
    if (resources.current.controller) return;
    const controller = new AbortController();
    resources.current.controller = controller;
    setPhase("starting");
    setError(null);
    try {
      const capture = await captureMicrophone({ signal: controller.signal, onSamples: paintSamples });
      if (resources.current.controller === controller) {
        resources.current.capture = capture;
        setPhase("recording");
      } else {
        capture.stop({ discard: true });
      }
    } catch (error) {
      if (resources.current.controller === controller) {
        resources.current.controller = null;
        setPhase("idle");
        if (!controller.signal.aborted) setError(error.message);
      }
    }
  }

  return { phase, error, reduceMotion, canvas, start, stop };
}

function drawMeter(canvas, levels) {
  if (!canvas) return;
  const context = canvas.getContext("2d");
  if (!context) return;
  const { width, height } = canvas;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#e5e7e4";
  const barWidth = 3;
  const pitch = 4;
  const shown = levels.slice(-Math.floor(width / pitch));
  shown.forEach((value, index) => {
    const bar = Math.max(2, Math.min(height, value * height * 1.8));
    context.fillRect(index * pitch, (height - bar) / 2, barWidth, bar);
  });
}
