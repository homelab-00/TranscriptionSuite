import React, { useRef, useEffect } from 'react';

interface AudioVisualizerProps {
  className?: string;
  /** When provided, draws real frequency data instead of the sine simulation */
  analyserNode?: AnalyserNode | null;
}

export const AudioVisualizer: React.FC<AudioVisualizerProps> = ({
  className = 'h-48',
  analyserNode,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;
    let t = 0;

    // Frequency data buffer (reused each frame when analyser is available)
    const freqData = analyserNode ? new Uint8Array(analyserNode.frequencyBinCount) : null;

    const resize = () => {
      if (canvas.parentElement) {
        canvas.width = canvas.parentElement.offsetWidth;
        canvas.height = canvas.parentElement.offsetHeight;
      }
    };

    resize();
    window.addEventListener('resize', resize);

    const drawSimulation = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const width = canvas.width;
      const height = canvas.height;
      const centerY = height / 2;
      const layers = 3;

      for (let j = 0; j < layers; j++) {
        ctx.beginPath();
        const color =
          j === 0
            ? 'rgba(34, 211, 238, 0.6)'
            : j === 1
              ? 'rgba(217, 70, 239, 0.5)'
              : 'rgba(251, 146, 60, 0.3)';
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';

        for (let x = 0; x < width; x += 2) {
          const amplitudeScale = height / 200;
          const y =
            centerY +
            Math.sin(x * 0.01 + t * (j + 1)) * (30 * amplitudeScale) * Math.sin(t * 0.5) +
            Math.sin(x * 0.03 + t * 2) * (10 * amplitudeScale);
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        if (j === 0) {
          ctx.lineTo(width, height);
          ctx.lineTo(0, height);
          ctx.fillStyle = 'rgba(34,211,238,0.05)';
          ctx.fill();
        }
      }
      t += 0.05;
    };

    const drawReal = () => {
      if (!analyserNode || !freqData) return;

      analyserNode.getByteFrequencyData(freqData);

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const width = canvas.width;
      const height = canvas.height;

      // Number of bars — use a subset of frequency bins for visual clarity
      const barCount = Math.min(freqData.length, Math.floor(width / 3));
      const barWidth = width / barCount;
      const step = Math.floor(freqData.length / barCount);

      for (let i = 0; i < barCount; i++) {
        const value = freqData[i * step];
        const normalized = value / 255;
        const barHeight = normalized * height * 0.85;

        // Gradient color: cyan at low frequencies → magenta at high
        const ratio = i / barCount;
        const r = Math.round(34 + ratio * 183); // 34 → 217
        const g = Math.round(211 - ratio * 141); // 211 → 70
        const b = Math.round(238 + ratio * 1); // 238 → 239
        const alpha = 0.4 + normalized * 0.5;

        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx.fillRect(i * barWidth + 1, height - barHeight, barWidth - 2, barHeight);
      }

      // Draw a waveform overlay using time-domain data
      const timeData = new Uint8Array(analyserNode.fftSize);
      analyserNode.getByteTimeDomainData(timeData);

      ctx.beginPath();
      ctx.strokeStyle = 'rgba(34, 211, 238, 0.8)';
      ctx.lineWidth = 1.5;
      ctx.lineJoin = 'round';

      const sliceWidth = width / timeData.length;
      for (let i = 0; i < timeData.length; i++) {
        const v = timeData[i] / 128.0;
        const y = (v * height) / 2;
        if (i === 0) ctx.moveTo(0, y);
        else ctx.lineTo(i * sliceWidth, y);
      }
      ctx.stroke();
    };

    const draw = () => {
      if (analyserNode && freqData) {
        drawReal();
      } else {
        drawSimulation();
      }
      animationId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationId);
    };
  }, [analyserNode]);

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
