/**
 * Utilities for estimating model loading progress based on status messages.
 *
 * Since accurate percentages are impractical (we can't hook into model download progress),
 * we use keyword-based phase detection to provide approximate progress feedback.
 */

export interface LoadingPhase {
  phase: number; // 0-100
  label: string;
}

/**
 * Estimate loading progress phase based on status message keywords.
 *
 * @param message - Status message from model loading backend
 * @returns Estimated progress percentage (0-100)
 */
export function estimateLoadingPhase(message: string): number {
  const msg = message.toLowerCase();

  // Phase 1: Initialization (0-10%)
  if (msg.includes('initializing') || msg.includes('starting')) {
    return 5;
  }

  // Phase 2: NeMo import (10-20%)
  if (msg.includes('importing nemo') || msg.includes('nemo toolkit')) {
    return 15;
  }

  // Phase 3: Model loading/downloading (20-70%)
  if (
    msg.includes('downloading') ||
    msg.includes('loading') ||
    msg.includes('from_pretrained') ||
    msg.includes('model:')
  ) {
    return 45;
  }

  // Phase 4: GPU transfer (70-85%)
  if (msg.includes('transferring') || msg.includes('gpu') || msg.includes('cuda')) {
    return 77;
  }

  // Phase 5: Warmup (85-95%)
  if (msg.includes('warmup') || msg.includes('warming')) {
    return 90;
  }

  // Phase 6: Complete (95-100%)
  if (msg.includes('ready') || msg.includes('complete') || msg.includes('loaded')) {
    return 98;
  }

  // Default: mid-progress
  return 50;
}

/**
 * Get a human-readable phase label based on progress percentage.
 */
export function getPhaseLabel(phase: number): string {
  if (phase < 10) return 'Initializing...';
  if (phase < 20) return 'Loading dependencies...';
  if (phase < 70) return 'Loading model...';
  if (phase < 85) return 'Preparing GPU...';
  if (phase < 95) return 'Warming up...';
  if (phase < 100) return 'Finalizing...';
  return 'Complete';
}
