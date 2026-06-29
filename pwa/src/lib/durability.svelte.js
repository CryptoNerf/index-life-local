// Durability state — whether the browser has granted persistent storage.
// Part of the "never a silent single copy" guarantee (alongside cloud backup
// and markdown export).

import { isPersisted, requestPersist } from './db.js';

export const durability = $state({ persisted: null });

export async function refreshPersisted() {
  durability.persisted = await isPersisted();
}

export async function enablePersist() {
  durability.persisted = await requestPersist();
  return durability.persisted;
}
