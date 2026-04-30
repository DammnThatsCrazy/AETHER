// =============================================================================
// Aether SDK — DEVICE FINGERPRINT COLLECTOR
// Generates a stable device fingerprint from browser signals.
// Only the hash is sent to backend — raw signals never leave the client.
// =============================================================================

export interface FingerprintComponents {
  canvasHash: string;
  webglRenderer: string;
  webglVendor: string;
  audioHash: string;
  screenResolution: string;
  colorDepth: number;
  timezone: string;
  language: string;
  languages: string[];
  platform: string;
  hardwareConcurrency: number;
  deviceMemory: number;
  touchSupport: boolean;
  fontHash: string;
  cookieEnabled: boolean;
  doNotTrack: string | null;
  pixelRatio: number;
}

const FP_STORAGE_KEY = '_aether_fp';
const FP_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

export class DeviceFingerprintCollector {
  private fingerprintId: string | null = null;
  private components: FingerprintComponents | null = null;

  async generate(): Promise<{ fingerprintId: string; components: FingerprintComponents }> {
    // Check cache first
    const cached = this.loadCached();
    if (cached) {
      this.fingerprintId = cached.fingerprintId;
      this.components = cached.components;
      return cached;
    }

    const components: FingerprintComponents = {
      canvasHash: await this.collectCanvas(),
      ...this.collectWebGL(),
      audioHash: await this.collectAudio(),
      screenResolution: `${screen.width}x${screen.height}`,
      colorDepth: screen.colorDepth,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      language: navigator.language,
      languages: [...(navigator.languages || [navigator.language])],
      platform: navigator.platform || '',
      hardwareConcurrency: navigator.hardwareConcurrency || 0,
      deviceMemory: (navigator as any).deviceMemory || 0,
      touchSupport: navigator.maxTouchPoints > 0,
      fontHash: this.collectFonts(),
      cookieEnabled: navigator.cookieEnabled,
      doNotTrack: navigator.doNotTrack,
      pixelRatio: window.devicePixelRatio || 1,
    };

    // Deterministic hash of all components
    const raw = JSON.stringify(components, Object.keys(components).sort());
    const fingerprintId = await this.sha256(raw);

    this.fingerprintId = fingerprintId;
    this.components = components;
    this.persistCache(fingerprintId, components);

    return { fingerprintId, components };
  }

  getFingerprintId(): string | null {
    return this.fingerprintId;
  }

  getComponents(): FingerprintComponents | null {
    return this.components;
  }

  // --- Signal Collectors ---

  private async collectCanvas(): Promise<string> {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 200;
      canvas.height = 50;
      const ctx = canvas.getContext('2d');
      if (!ctx) return '';
      ctx.textBaseline = 'top';
      ctx.font = '14px Arial';
      ctx.fillStyle = '#f60';
      ctx.fillRect(0, 0, 200, 50);
      ctx.fillStyle = '#069';
      ctx.fillText('Aether FP', 2, 2);
      ctx.fillStyle = 'rgba(102,204,0,0.7)';
      ctx.fillText('Canvas Test', 4, 18);
      return await this.sha256(canvas.toDataURL());
    } catch {
      return '';
    }
  }

  private collectWebGL(): { webglRenderer: string; webglVendor: string } {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      if (!gl) return { webglRenderer: '', webglVendor: '' };
      const ext = (gl as WebGLRenderingContext).getExtension('WEBGL_debug_renderer_info');
      if (!ext) return { webglRenderer: '', webglVendor: '' };
      return {
        webglRenderer: (gl as WebGLRenderingContext).getParameter(ext.UNMASKED_RENDERER_WEBGL) || '',
        webglVendor: (gl as WebGLRenderingContext).getParameter(ext.UNMASKED_VENDOR_WEBGL) || '',
      };
    } catch {
      return { webglRenderer: '', webglVendor: '' };
    }
  }

  private async collectAudio(): Promise<string> {
    try {
      const ctx = new OfflineAudioContext(1, 44100, 44100);
      const osc = ctx.createOscillator();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(10000, ctx.currentTime);
      const comp = ctx.createDynamicsCompressor();
      osc.connect(comp);
      comp.connect(ctx.destination);
      osc.start(0);
      const buffer = await ctx.startRendering();
      const samples = buffer.getChannelData(0).slice(4500, 5000);
      let sum = 0;
      for (let i = 0; i < samples.length; i++) sum += Math.abs(samples[i]);
      return await this.sha256(sum.toString());
    } catch {
      return '';
    }
  }

  private collectFonts(): string {
    const testFonts = [
      'Arial', 'Verdana', 'Times New Roman', 'Courier New', 'Georgia',
      'Palatino', 'Garamond', 'Comic Sans MS', 'Trebuchet MS', 'Arial Black',
      'Impact', 'Lucida Console', 'Tahoma', 'Lucida Sans', 'Century Gothic',
      'Bookman Old Style', 'Brush Script MT', 'Copperplate', 'Papyrus',
      'Futura', 'Helvetica Neue', 'Optima', 'Didot', 'American Typewriter',
    ];
    try {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      if (!ctx) return '';
      const baseline = 'monospace';
      const testStr = 'mmmmmmmmlli';
      ctx.font = `72px ${baseline}`;
      const baseWidth = ctx.measureText(testStr).width;
      const detected: string[] = [];
      for (const font of testFonts) {
        ctx.font = `72px '${font}', ${baseline}`;
        if (ctx.measureText(testStr).width !== baseWidth) detected.push(font);
      }
      return detected.join(',');
    } catch {
      return '';
    }
  }

  // --- SHA-256 ---

  private async sha256(input: string): Promise<string> {
    try {
      const encoder = new TextEncoder();
      const data = encoder.encode(input);
      const hash = await crypto.subtle.digest('SHA-256', data);
      return Array.from(new Uint8Array(hash))
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('');
    } catch {
      // Fallback: simple FNV-1a hash
      let h = 0x811c9dc5;
      for (let i = 0; i < input.length; i++) {
        h ^= input.charCodeAt(i);
        h = Math.imul(h, 0x01000193);
      }
      return (h >>> 0).toString(16).padStart(8, '0');
    }
  }

  // --- Cache ---

  private loadCached(): { fingerprintId: string; components: FingerprintComponents } | null {
    try {
      const raw = localStorage.getItem(FP_STORAGE_KEY);
      if (!raw) return null;
      const cached = JSON.parse(raw);
      if (Date.now() - cached.timestamp > FP_TTL_MS) {
        localStorage.removeItem(FP_STORAGE_KEY);
        return null;
      }
      return { fingerprintId: cached.fingerprintId, components: cached.components };
    } catch {
      return null;
    }
  }

  private persistCache(fingerprintId: string, components: FingerprintComponents): void {
    try {
      localStorage.setItem(
        FP_STORAGE_KEY,
        JSON.stringify({ fingerprintId, components, timestamp: Date.now() })
      );
    } catch {
      // Silent fail — fingerprint still works without cache
    }
  }
}
