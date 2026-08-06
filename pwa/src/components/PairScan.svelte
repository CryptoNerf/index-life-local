<script>
  // QR scanner for the pairing code the desktop shows.
  //
  // Two decoders, because the native one covers only half the phones:
  //   * BarcodeDetector — Chrome/Android, no bundle weight;
  //   * jsQR — everything else, iOS Safari above all, where BarcodeDetector
  //     does not exist. It is loaded only when actually needed, so Android
  //     never pays for it.
  //
  // Before the fallback, an iPhone had to hand-type a 62-character key with
  // hyphens — the primary way to connect a phone on the platform where it was
  // hardest to do.
  import { onMount, onDestroy } from 'svelte';

  let { onscan, oncancel } = $props();

  let video = $state(null);
  let err = $state('');
  let starting = $state(true);
  let stream = null;
  let raf = 0;
  let done = false;
  let canvas = null;

  function stop() {
    done = true;
    cancelAnimationFrame(raf);
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  function found(text) {
    if (done || !text) return;
    stop();
    onscan(text);
  }

  // jsQR needs pixels, so frames go through an offscreen canvas sized to the
  // video. Downscaled a little: a QR fills a good part of the frame and the
  // decoder is much faster on fewer pixels.
  function grabFrame() {
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) return null;
    const scale = Math.min(1, 640 / Math.max(w, h));
    const cw = Math.round(w * scale);
    const ch = Math.round(h * scale);
    if (!canvas) canvas = document.createElement('canvas');
    if (canvas.width !== cw || canvas.height !== ch) {
      canvas.width = cw;
      canvas.height = ch;
    }
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, cw, ch);
    return ctx.getImageData(0, 0, cw, ch);
  }

  async function scanLoop() {
    let detect;
    if (typeof BarcodeDetector !== 'undefined') {
      const detector = new BarcodeDetector({ formats: ['qr_code'] });
      detect = async () => {
        const codes = await detector.detect(video);
        return codes.length ? codes[0].rawValue : null;
      };
    } else {
      const { default: jsQR } = await import('jsqr');
      detect = async () => {
        const frame = grabFrame();
        if (!frame) return null;
        const code = jsQR(frame.data, frame.width, frame.height, {
          inversionAttempts: 'dontInvert'   // a screen shows a normal QR
        });
        return code?.data || null;
      };
    }

    const tick = async () => {
      if (done) return;
      try {
        const value = await detect();
        if (value) return found(value);
      } catch {
        /* one bad frame — keep scanning */
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  }

  onMount(async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
      });
      video.srcObject = stream;
      // iOS needs playsinline + muted (both set on the element) and refuses
      // to autoplay otherwise; the await is what actually starts frames.
      await video.play();
      starting = false;
      await scanLoop();
    } catch (e) {
      starting = false;
      err = e?.name === 'NotAllowedError'
        ? 'Нет доступа к камере — разрешите его в настройках браузера или введите код текстом.'
        : (e?.message || 'Камера недоступна');
    }
  });

  onDestroy(stop);
</script>

{#if err}
  <p class="cloud-error">⚠ {err}</p>
{:else}
  <!-- svelte-ignore a11y_media_has_caption -->
  <video bind:this={video} class="pair-video" playsinline muted></video>
  <p class="hint">
    {starting ? 'Включаем камеру…' : 'Наведите камеру на QR-код на экране компьютера.'}
  </p>
{/if}
<button class="link-btn" onclick={oncancel}>Отмена</button>
