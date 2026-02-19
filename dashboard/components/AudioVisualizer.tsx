import React, { useRef, useEffect, useCallback } from 'react';

interface AudioVisualizerProps {
  className?: string;
  /** When provided, draws real frequency data instead of the idle simulation */
  analyserNode?: AnalyserNode | null;
}

const BAR_COUNT = 64;
const BAR_GAP = 3;
const IDLE_LERP = 0.08;
const LIVE_LERP = 0.18;
const TARGET_UPDATE_INTERVAL = 8; // frames between idle target recalculation

export const AudioVisualizer: React.FC<AudioVisualizerProps> = ({
  className = 'h-48',
  analyserNode,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const barsRef = useRef<number[]>([]);
  const targetBarsRef = useRef<number[]>([]);
  const tickRef = useRef(0);

  const initBars = useCallback(() => {
    if (barsRef.current.length === 0) {
      barsRef.current = Array.from({ length: BAR_COUNT }, () => Math.random() * 0.15);
      targetBarsRef.current = Array.from({ length: BAR_COUNT }, () => Math.random() * 0.15);
    }
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    initBars();

    const freqData = analyserNode ? new Uint8Array(analyserNode.frequencyBinCount) : null;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      if (canvas.parentElement) {
        canvas.width = canvas.parentElement.offsetWidth * dpr;
        canvas.height = canvas.parentElement.offsetHeight * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    };

    resize();
    window.addEventListener('resize', resize);

    const drawBars = () => {
      const w = canvas.width / (window.devicePixelRatio || 1);
      const h = canvas.height / (window.devicePixelRatio || 1);
      ctx.clearRect(0, 0, w, h);

      tickRef.current++;
      const tick = tickRef.current;
      const bars = barsRef.current;
      const targets = targetBarsRef.current;

      if (analyserNode && freqData) {
        // ── Live audio mode: drive bars from frequency data ──
        analyserNode.getByteFrequencyData(freqData);
        const step = Math.max(1, Math.floor(freqData.length / BAR_COUNT));
        for (let i = 0; i < BAR_COUNT; i++) {
          targets[i] = freqData[i * step] / 255;
        }
        for (let i = 0; i < BAR_COUNT; i++) {
          bars[i] += (targets[i] - bars[i]) * LIVE_LERP;
        }
      } else {
        // ── Idle breathing wave animation ──
        if (tick % TARGET_UPDATE_INTERVAL === 0) {
          for (let i = 0; i < BAR_COUNT; i++) {
            const wave = Math.sin((i / BAR_COUNT) * Math.PI * 2 + tick * 0.02) * 0.3 + 0.3;
            const noise = Math.random() * 0.4;
            targets[i] = wave + noise * 0.5;
          }
        }
        for (let i = 0; i < BAR_COUNT; i++) {
          bars[i] += (targets[i] - bars[i]) * IDLE_LERP;
        }
      }

      // ── Draw rounded bars centered vertically ──
      const barWidth = (w - BAR_GAP * (BAR_COUNT - 1)) / BAR_COUNT;
      const centerY = h / 2;
      const radius = barWidth / 2;

      for (let i = 0; i < BAR_COUNT; i++) {
        const val = bars[i];
        const barH = Math.max(4, val * h * 0.8);
        const x = i * (barWidth + BAR_GAP);

        // Gradient from cyan to magenta based on bar position
        const ratio = i / BAR_COUNT;
        const r = Math.round(20 + ratio * 200);
        const g = Math.round(200 - ratio * 120);
        const b = Math.round(230 - ratio * 60 + ratio * 100);

        const gradient = ctx.createLinearGradient(x, centerY - barH / 2, x, centerY + barH / 2);
        gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.9)`);
        gradient.addColorStop(0.5, `rgba(${r}, ${g}, ${b}, 1)`);
        gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0.6)`);

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.roundRect(x, centerY - barH / 2, barWidth, barH, radius);
        ctx.fill();

        // Glow effect
        ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.3)`;
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
    };

    const draw = () => {
      drawBars();
      animationRef.current = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationRef.current);
    };
  }, [analyserNode, initBars]);

  return (
    <div
      className={`relative w-full overflow-hidden rounded-xl border border-white/5 bg-black/20 shadow-inner ${className}`}
    >
      {/* Subtle grid overlay */}
      <div
        className="pointer-events-none absolute inset-0 opacity-10"
        style={{
          backgroundImage:
            'linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }}
      ></div>
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
};
