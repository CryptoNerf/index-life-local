<script>
  // QR scanner for the pairing code shown on the desktop. Uses the native
  // BarcodeDetector (Chrome/Android; no library, no bundle weight). On
  // browsers without it (iOS Safari) the caller's manual text input is the
  // fallback — this component just reports 'no-detector' so the UI says so.
  import { onMount, onDestroy } from 'svelte';

  let { onscan, oncancel } = $props();

  let video = $state(null);
  let err = $state('');
  let stream = null;
  let raf = 0;
  let done = false;

  onMount(async () => {
    if (typeof BarcodeDetector === 'undefined') {
      err = 'no-detector';
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
      });
      video.srcObject = stream;
      await video.play();
      const detector = new BarcodeDetector({ formats: ['qr_code'] });
      const tick = async () => {
        if (done) return;
        try {
          const codes = await detector.detect(video);
          if (codes.length && codes[0].rawValue) {
            done = true;
            onscan(codes[0].rawValue);
            return;
          }
        } catch {
          /* a frame failed to decode — keep scanning */
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    } catch (e) {
      err = e?.message || 'Камера недоступна';
    }
  });

  onDestroy(() => {
    done = true;
    cancelAnimationFrame(raf);
    stream?.getTracks().forEach((t) => t.stop());
  });
</script>

{#if err === 'no-detector'}
  <p class="hint">Сканер не поддерживается этим браузером — введите код с компьютера текстом ниже.</p>
{:else if err}
  <p class="cloud-error">⚠ {err}</p>
{:else}
  <!-- svelte-ignore a11y_media_has_caption -->
  <video bind:this={video} class="pair-video" playsinline muted></video>
  <p class="hint">Наведите камеру на QR-код на экране компьютера.</p>
{/if}
<button class="link-btn" onclick={oncancel}>Отмена</button>
