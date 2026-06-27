<script>
  import MoodChart from '../components/MoodChart.svelte';
  import BarChart from '../components/BarChart.svelte';
  import Heatmap from '../components/Heatmap.svelte';
  import Rose from '../components/Rose.svelte';
  import Ridgeline from '../components/Ridgeline.svelte';
  import Spiral from '../components/Spiral.svelte';
  import Words from '../components/Words.svelte';
  import { allEntries } from '../lib/db.js';
  import { distribution, monthlyAverages } from '../lib/stats.js';

  let entries = $state([]);

  $effect(() => {
    allEntries().then((list) => {
      entries = list
        .filter((e) => !e.deleted && e.rating >= 1)
        .sort((a, b) => a.date.localeCompare(b.date));
    });
  });

  const dist = $derived(distribution(entries));
  const monthly = $derived(monthlyAverages(entries));
  const maxDist = $derived(Math.max(1, ...dist.map((d) => d.value)));
</script>

<section class="screen chart">
  <h2 class="screen-title">Настроение</h2>

  {#if entries.length === 0}
    <p class="empty">Пока нет записей для графиков.<br />Оцените хотя бы пару дней.</p>
  {:else}
    <div class="chart-card">
      <div class="chart-title">Динамика</div>
      <MoodChart {entries} />
    </div>

    <div class="chart-card">
      <div class="chart-title">Распределение оценок</div>
      <BarChart bars={dist} max={maxDist} />
    </div>

    <div class="chart-card">
      <div class="chart-title">По месяцам</div>
      <BarChart bars={monthly} max={10} />
    </div>

    <div class="chart-card">
      <div class="chart-title">Ритм — дни недели × месяцы</div>
      <Heatmap {entries} />
    </div>

    <div class="chart-card">
      <div class="chart-title">Роза по дням недели</div>
      <Rose {entries} />
    </div>

    <div class="chart-card">
      <div class="chart-title">Хребты по месяцам</div>
      <Ridgeline {entries} />
    </div>

    <div class="chart-card">
      <div class="chart-title">Спираль года</div>
      <Spiral {entries} />
    </div>

    <div class="chart-card">
      <div class="chart-title">Слова</div>
      <Words {entries} />
    </div>
  {/if}
</section>
