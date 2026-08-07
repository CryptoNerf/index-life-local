<script>
  import RatingCubes from '../components/RatingCubes.svelte';
  import MoodFace from '../components/MoodFace.svelte';
  import { getEntry } from '../lib/db.js';
  import { moodStore, saveEntry, removeEntry, restoreEntry } from '../lib/store.svelte.js';
  import { scheduleSync, syncState } from '../lib/sync-state.svelte.js';
  import { isUnlocked } from '../lib/vault.js';
  import { loadDraft, saveDraft, clearDraft, editorStateFor } from '../lib/drafts.js';
  import { currentStreak } from '../lib/stats.js';
  import { todayISO, prettyDate, isToday, addDays, pluralDays, timeAgo } from '../lib/mood.js';

  // Bindable so date navigation here propagates to the app (and "День" in the
  // nav resets it to today). Any past day can be opened to backfill it.
  let { date = $bindable(todayISO()) } = $props();

  let rating = $state(0);
  let note = $state('');
  let saved = $state(false);
  // The day exists here only as a tombstone: it was deleted on another
  // device. A tombstone keeps its old text (that is how the deletion travels
  // to devices that still hold the entry), so loading it into the editor
  // would show content the user deliberately deleted — and any save would
  // push it back to the desktop, resurrecting it.
  let deletedElsewhere = $state(false);
  // A saved (live) entry exists for this day — the only case where deleting
  // means anything.
  let hasEntry = $state(false);
  // Deleted right here, a moment ago: worth a softer word and a plain undo
  // rather than the "on another device" explanation.
  let justDeleted = $state(false);

  // Where the entry stands with the cloud, said on the screen where writing
  // happens. Until now the only sync status lived three blocks down the
  // settings screen, so after tapping Save there was no way to tell whether
  // the day had left the phone. Silent when cloud sync isn't set up — the
  // durability banner already owns that case.
  const cloudOn = $derived(syncState.lastSyncedAt >= 0 && isUnlocked());
  const cloudNote = $derived(
    !cloudOn ? ''
      : syncState.status === 'syncing' ? 'отправляю в облако…'
      : syncState.status === 'auth' ? 'не отправлено — нужен вход в облако'
      : syncState.status === 'error' ? 'не отправлено — попробую позже'
      : syncState.lastSyncedAt ? `в облаке · ${timeAgo(syncState.lastSyncedAt)}`
      : ''
  );

  const TODAY = todayISO();
  function step(n) {
    const next = addDays(date, n);
    date = next > TODAY ? TODAY : next; // never log a future day
  }

  // Logging streak — the little daily-habit reward. Reactive off the shared
  // store, so it bumps the moment today's entry is saved.
  const streak = $derived(currentStreak(moodStore.entries, TODAY));

  // Load whenever the target day changes. An unsaved draft (from a previous
  // visit where the user typed but didn't save) takes priority over the saved
  // entry — but only while it's the fresher of the two: an entry edited on
  // another device and synced later must not be hidden behind a stale draft
  // (see draftIsFresh).
  $effect(() => {
    const d = date;
    // Also re-read when the stored entries change, not just when the date
    // does: a sync landing a newer version of the day you are looking at, or
    // a restore from the localStorage mirror after an eviction, used to leave
    // this screen showing stale (or empty) content until you navigated away
    // and back. Typing is safe — a draft being edited is always the freshest,
    // and draftIsFresh keeps it on top.
    moodStore.entries;
    getEntry(d).then((e) => {
      const view = editorStateFor(e, loadDraft(d));
      rating = view.rating;
      note = view.note;
      deletedElsewhere = view.deletedElsewhere;
      hasEntry = !!e && !e.deleted;
      justDeleted = false;   // a fresh day, whatever happened on the last one
    });
  });

  // Persist every edit immediately so leaving this screen never drops text.
  function touch() {
    saveDraft(date, { rating, note });
  }

  function setRating(v) {
    rating = v;
    deletedElsewhere = false;   // writing again is a deliberate revival
    justDeleted = false;
    touch();
  }

  // Soft delete, like the desktop: the row stays as a tombstone so the
  // deletion travels to the other devices instead of the day quietly coming
  // back on the next merge. No modal — the undo below is the safety net, and
  // a tombstone keeps the text, so nothing is actually lost either way.
  async function remove() {
    const tomb = await removeEntry(date);
    if (!tomb) return;
    clearDraft(date);
    rating = 0;
    note = '';
    hasEntry = false;
    justDeleted = true;
    deletedElsewhere = false;
    scheduleSync();
  }

  async function undoDelete() {
    const rec = await restoreEntry(date);
    if (!rec) return;
    rating = rec.rating;
    note = rec.note ?? '';
    hasEntry = true;
    justDeleted = false;
    deletedElsewhere = false;
    scheduleSync();
  }

  async function save() {
    if (!rating) return;
    await saveEntry({ date, rating, note });
    clearDraft(date);
    scheduleSync(); // push to the cloud shortly after (debounced)
    saved = true;
    setTimeout(() => (saved = false), 1500);
  }
</script>

<section class="screen capture">
  <header class="cap-head">
    <div class="cap-nav">
      <button class="cap-arrow" onclick={() => step(-1)} aria-label="Предыдущий день">‹</button>
      <label class="cap-date">
        {prettyDate(date)}<span class="cap-date-caret">▾</span>
        <input type="date" class="cap-date-input" bind:value={date} max={TODAY} />
      </label>
      <button class="cap-arrow" onclick={() => step(1)} disabled={date >= TODAY}
              aria-label="Следующий день">›</button>
    </div>
    {#if isToday(date)}<div class="cap-today">сегодня</div>{/if}
    {#if streak >= 2 && isToday(date)}
      <div class="cap-streak">▪ {streak} {pluralDays(streak)} подряд</div>
    {/if}
    <MoodFace {rating} size={92} />
  </header>

  {#if justDeleted}
    <p class="cap-deleted">
      Запись удалена.
      <button class="link-btn cap-undo" onclick={undoDelete}>Вернуть</button>
    </p>
  {:else if deletedElsewhere}
    <p class="cap-deleted">
      Эта запись удалена на другом устройстве.
      <button class="link-btn cap-undo" onclick={undoDelete}>Вернуть</button>
    </p>
  {/if}

  <RatingCubes value={rating} onchange={setRating} />

  <textarea class="note" bind:value={note} oninput={() => { deletedElsewhere = false; touch(); }}
            placeholder="Как прошёл день?"></textarea>

  <button class="save-btn" class:is-saved={saved} disabled={!rating} onclick={save}>
    {saved ? 'Сохранено ✓' : 'Сохранить'}
  </button>

  {#if cloudNote}<p class="cap-cloud">{cloudNote}</p>{/if}

  {#if hasEntry}
    <button class="link-btn cap-delete" onclick={remove}>Удалить запись</button>
  {/if}
</section>
