import React, { useRef, useEffect } from 'react';

interface AudioVisualizerProps {
  className?: string;
}

export const AudioVisualizer: React.FC<AudioVisualizerProps> = ({ className = "h-48" }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;
    let t = 0;

    const resize = () => {
      // Use offsetWidth/Height to get accurate pixel size of the container
      if (canvas.parentElement) {
        canvas.width = canvas.parentElement.offsetWidth;
        canvas.height = canvas.parentElement.offsetHeight;
      }
    };
    
    // Initial resize and listener
    resize();
    window.addEventListener('resize', resize);

    const draw = () => {
      // Clear with transparency
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      const width = canvas.width;
      const height = canvas.height;
      const centerY = height / 2;

      // Simulated frequencies
      const layers = 3;
      
      for (let j = 0; j < layers; j++) {
        ctx.beginPath();
        const color = j === 0 ? 'rgba(34, 211, 238, 0.6)' : // Cyan
                      j === 1 ? 'rgba(217, 70, 239, 0.5)' : // Magenta
                      'rgba(251, 146, 60, 0.3)'; // Orange
                      
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round'; // Smooth curves

        // Draw sine waves with noise
        for (let x = 0; x < width; x+=2) {
            // Complex wave function to simulate voice
            // We scale the amplitude based on height to make it look good at any size
            const amplitudeScale = height / 200; 
            
            const y = centerY + 
                Math.sin(x * 0.01 + t * (j + 1)) * (30 * amplitudeScale) * Math.sin(t * 0.5) +
                Math.sin(x * 0.03 + t * 2) * (10 * amplitudeScale);
            
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        
        // Fill effect for bottom layer
        if (j === 0) {
            ctx.lineTo(width, height);
            ctx.lineTo(0, height);
            ctx.fillStyle = 'linear-gradient(180deg, rgba(34,211,238,0.1) 0%, rgba(34,211,238,0) 100%)';
            ctx.fill();
        }
      }

      t += 0.05;
      animationId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationId);
    };
  }, []);

  return (
    <div className={`w-full relative rounded-xl overflow-hidden bg-black/20 border border-white/5 shadow-inner ${className}`}>
        {/* Subtle grid overlay */}
        <div className="absolute inset-0 opacity-10 pointer-events-none" style={{ backgroundImage: 'linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)', backgroundSize: '20px 20px' }}></div>
        <canvas ref={canvasRef} className="w-full h-full block" />
    </div>
  );
};