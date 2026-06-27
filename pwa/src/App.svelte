<script>
  import Capture from './screens/Capture.svelte';
  import Feed from './screens/Feed.svelte';
  import Settings from './screens/Settings.svelte';
  import BottomNav from './components/BottomNav.svelte';
  import { todayISO } from './lib/mood.js';

  let screen = $state('capture');
  let editDate = $state(todayISO());

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
  {#if screen === 'capture'}
    <Capture date={editDate} />
  {:else if screen === 'feed'}
    <Feed onopen={openDay} />
  {:else}
    <Settings />
  {/if}
</div>

<BottomNav {screen} onnavigate={navigate} />
