<script>
  import { onMount } from 'svelte';
  import Capture from './screens/Capture.svelte';
  import Feed from './screens/Feed.svelte';
  import Chart from './screens/Chart.svelte';
  import Settings from './screens/Settings.svelte';
  import BottomNav from './components/BottomNav.svelte';
  import DurabilityBanner from './components/DurabilityBanner.svelte';
  import { todayISO } from './lib/mood.js';
  import { refreshEntries } from './lib/store.svelte.js';
  import { runSync } from './lib/sync-state.svelte.js';

  let screen = $state('capture');
  let editDate = $state(todayISO());

  onMount(() => {
    refreshEntries();
    // Sync on open if cloud encryption is already set up — silent, so a user
    // who hasn't connected sees nothing and a lapsed session just no-ops.
    runSync({ silent: true });
  });

  function openDay(date) {
    editDate = date;
    screen = 'capture';
  }

  function navigate(s) {
    // Tapping "День" always returns to today.
    if (s === 'capture') editDate = todayISO();
    screen = s;
  }
</script>

<div class="app">
  {#if screen !== 'settings'}
    <DurabilityBanner onfix={() => navigate('settings')} />
  {/if}

  {#if screen === 'capture'}
    <Capture bind:date={editDate} />
  {:else if screen === 'feed'}
    <Feed onopen={openDay} />
  {:else if screen === 'chart'}
    <Chart />
  {:else}
    <Settings />
  {/if}
</div>

<BottomNav {screen} onnavigate={navigate} />
