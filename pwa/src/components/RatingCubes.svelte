<script>
  // Ten cubes that fill up to the chosen value — the desktop's rating control,
  // sized for thumbs. Tap a cube to set; drag across to scrub.
  let { value = 0, onchange } = $props();

  function set(v) {
    if (v !== value) {
      onchange?.(v);
      if (navigator.vibrate) navigator.vibrate(4);
    }
  }

  function fromTouch(e) {
    const t = e.touches?.[0];
    if (!t) return;
    const el = document.elementFromPoint(t.clientX, t.clientY);
    const v = el?.dataset?.value;
    if (v) set(Number(v));
  }
</script>

<div class="cubes" ontouchmove={fromTouch} role="group" aria-label="Оценка дня от 1 до 10">
  {#each Array(10) as _, i}
    <button type="button" class="cube" class:filled={value >= i + 1}
            data-value={i + 1} aria-label={`${i + 1}`} onclick={() => set(i + 1)}></button>
  {/each}
</div>
