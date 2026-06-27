<script>
  import { moodMouth } from '../lib/mood.js';

  let { rating = 0, size = 80 } = $props();
  const mouth = $derived(moodMouth(rating));
</script>

<svg class="mood-face" viewBox="0 0 80 80" width={size} height={size}
     role="img" aria-label={rating ? `${rating} из 10` : 'нет оценки'}>
  <circle cx="40" cy="40" r="33" fill="none" stroke="currentColor" stroke-width="3" />
  <circle cx="30" cy="34" r="3.4" fill="currentColor" />
  <circle cx="50" cy="34" r="3.4" fill="currentColor" />
  <path d={`M27,52 Q40,${52 + mouth} 53,52`} fill="none"
        stroke="currentColor" stroke-width="3.4" stroke-linecap="round" />
</svg>
