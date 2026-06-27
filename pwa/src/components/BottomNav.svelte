<script>
  let { screen, onnavigate } = $props();

  const tabs = [
    { id: 'capture', label: 'День', ico: '✎' },
    { id: 'feed', label: 'Дни', ico: '☰' },
    { id: 'chart', label: 'График', ico: '∿' },
    { id: 'settings', label: 'Ещё', ico: '•••' }
  ];
</script>

<nav class="bottom-nav">
  {#each tabs as tab}
    <button class="nav-btn" class:active={screen === tab.id}
            onclick={() => onnavigate(tab.id)}>
      <span class="nav-ico">{tab.ico}</span>
      <span>{tab.label}</span>
    </button>
  {/each}
</nav>
