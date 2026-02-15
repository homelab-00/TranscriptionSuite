import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Activity, Mic, Minimize2, Waves, Zap, Cpu, BarChart3 } from 'lucide-react';
import { AudioVisualizer } from '../AudioVisualizer';
import { Button } from '../ui/Button';

interface FullscreenVisualizerProps {
  isOpen: boolean;
  onClose: () => void;
  analyserNode?: AnalyserNode | null;
}

export const FullscreenVisualizer: React.FC<FullscreenVisualizerProps> = ({ isOpen, onClose, analyserNode }) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;

    if (isOpen) {
      setIsRendered(true);
      // Double RAF to ensure DOM paint before transition
      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
            setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), 500);
    }

    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
    };
  }, [isOpen]);

  if (!isRendered) return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
        
        {/* Deep Backdrop Blur */}
        <div 
            className={`absolute inset-0 bg-slate-900/80 backdrop-blur-3xl transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        />

        {/* Content Container */}
        <div className={`
            relative w-full h-full flex flex-col p-6 lg:p-10
            transition-all duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]
            ${isVisible ? 'scale-100 opacity-100' : 'scale-95 opacity-0'}
        `}>
            
            {/* Header / HUD Top */}
            <div className="flex-none flex items-center justify-between mb-8 animate-in slide-in-from-top-4 duration-700 delay-100 fill-mode-forwards">
                <div className="flex items-center gap-6">
                    <div className="flex items-center gap-3">
                        <div className="p-3 rounded-2xl bg-accent-cyan/10 border border-accent-cyan/20 text-accent-cyan shadow-[0_0_15px_rgba(34,211,238,0.2)]">
                            <Activity size={24} className="animate-pulse" />
                        </div>
                        <div>
                            <h2 className="text-2xl font-bold text-white tracking-tight">Spectral Analysis</h2>
                            <div className="flex items-center gap-2">
                                <span className={`w-1.5 h-1.5 rounded-full ${analyserNode ? 'bg-green-400 shadow-[0_0_5px_#4ade80]' : 'bg-slate-500'}`}></span>
                                <span className={`text-xs font-mono tracking-widest uppercase ${analyserNode ? 'text-green-400' : 'text-slate-500'}`}>{analyserNode ? 'Live Input Active' : 'No Input'}</span>
                            </div>
                        </div>
                    </div>
                    
                    {/* Decorative HUD Lines */}
                    <div className="hidden lg:flex items-center gap-1 opacity-30">
                         <div className="w-2 h-8 bg-white/20 skew-x-[-12deg]"></div>
                         <div className="w-2 h-8 bg-white/20 skew-x-[-12deg]"></div>
                         <div className="w-2 h-8 bg-white/20 skew-x-[-12deg]"></div>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                     <div className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-xs font-mono text-slate-400 hidden sm:block">
                        BUFFER_SIZE: 4096
                     </div>
                     <Button 
                        variant="secondary" 
                        onClick={onClose}
                        className="rounded-full h-12 w-12 border-white/10 hover:bg-white/10 hover:border-white/20"
                        icon={<Minimize2 size={20} />}
                     />
                </div>
            </div>

            {/* Main Visualizer Area */}
            <div className="flex-1 min-h-0 relative rounded-3xl overflow-hidden border border-white/10 bg-black/40 shadow-2xl animate-in zoom-in-95 duration-700 delay-150 fill-mode-forwards group">
                 {/* Top Left Corner Accent */}
                 <div className="absolute top-0 left-0 w-32 h-32 bg-accent-cyan/5 rounded-br-full blur-2xl pointer-events-none"></div>
                 
                 <AudioVisualizer className="h-full w-full" analyserNode={analyserNode} />
                 
                 {/* Overlay Gradient for depth */}
                 <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-black/20 pointer-events-none"></div>
                 
                 {/* Floating Frequency Labels */}
                 <div className="absolute bottom-6 left-8 flex gap-8 text-xs font-mono text-slate-500 select-none">
                    <span>20Hz</span>
                    <span>100Hz</span>
                    <span>500Hz</span>
                    <span>1kHz</span>
                    <span>5kHz</span>
                    <span>20kHz</span>
                 </div>
            </div>

            {/* Footer / HUD Bottom */}
            <div className="flex-none mt-8 grid grid-cols-1 md:grid-cols-4 gap-4 animate-in slide-in-from-bottom-4 duration-700 delay-200 fill-mode-forwards">
                <HudCard 
                    icon={<Mic size={18} />}
                    label="Input Source"
                    value={analyserNode ? 'Live Input' : 'No Input'}
                    subValue="Channel 1 (Mono)"
                    color="cyan"
                />
                <HudCard 
                    icon={<Waves size={18} />}
                    label="Sample Rate"
                    value={analyserNode ? `${(analyserNode.context.sampleRate / 1000).toFixed(1)} kHz` : '— kHz'}
                    subValue="32-bit Float"
                    color="magenta"
                />
                <HudCard 
                    icon={<Zap size={18} />}
                    label="FFT Size"
                    value={analyserNode ? `${analyserNode.fftSize}` : '—'}
                    subValue={analyserNode ? `${analyserNode.frequencyBinCount} bins` : '—'}
                    color="orange"
                />
                 <HudCard 
                    icon={<Cpu size={18} />}
                    label="Processing"
                    value="FFT (Fast)"
                    subValue="Window: Hann"
                    color="blue"
                />
            </div>

        </div>
    </div>,
    document.body
  );
};

// Helper component for the stats row
const HudCard = ({ icon, label, value, subValue, color }: any) => {
    const colors = {
        cyan: 'text-accent-cyan bg-accent-cyan/10 border-accent-cyan/20',
        magenta: 'text-accent-magenta bg-accent-magenta/10 border-accent-magenta/20',
        orange: 'text-accent-orange bg-accent-orange/10 border-accent-orange/20',
        blue: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
    };

    return (
        <div className="bg-glass-100 border border-white/5 rounded-xl p-4 flex items-center gap-4 hover:bg-white/5 transition-colors">
            <div className={`p-3 rounded-lg ${colors[color]} border`}>
                {icon}
            </div>
            <div>
                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold mb-0.5">{label}</div>
                <div className="text-sm font-semibold text-white">{value}</div>
                <div className="text-xs text-slate-400 font-mono opacity-70">{subValue}</div>
            </div>
        </div>
    );
};