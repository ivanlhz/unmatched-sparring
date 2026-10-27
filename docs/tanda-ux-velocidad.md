# Next batch: UX and speed (agreed with Iván on 27/10/2026)

## 1. Speed (target: < 1 s per button, the human's and the bot's alike)
Iván notices lag both when he presses his own action and during the bot's turn.
- Measure first: time every `Session.handle` and every `call_lua` (a log of times, with a `--timing` flag). Report the slow buttons with a breakdown.
- Likely causes:
  - several separate Lua round trips per button (sync_human reads twice with `settle_wait` 0.4 s, sync_positions, reading/writing each dial separately, flush/reconcile);
  - `_settle` with 6 × 0.4 s;
  - a fresh TCP connection per message.
- Fixes:
  - one composite read builder (a snapshot of hands, discards, pieces, dials and face-down cards in a single call);
  - write all dials in a single call, then verify them in a single read;
  - sleep only when a read actually disagrees;
  - shorten `settle_wait` once the measurements confirm it is safe.

### Live measurement (27/10, Iván's real TTS)
- Every message to TTS costs **~0.5 s** of fixed latency (TTS takes ~470 ms to call back; our send and connection-close take ~0 ms). An error reply takes just as long, so it is not caused by `sendExternalMessage`.
- **Pipelining does not help:** 4 scripts sent back to back took 0.8 / 1.6 / 2.4 / 3.2 s. TTS handles ~1 message per tick.
- Conclusion: the only lever is **the number of messages per button**. With 8-15 calls per button you get 4-7 s.

### Target design
1. **The click brings the snapshot:** the panel object's `onClick` (Lua inside TTS) gathers the table state (hands by count, discards, face-down cards, pieces, dials) and sends it in the same `sendExternalMessage({event=..., snapshot=...})`. Python never asks before deciding.
2. **One message out per button:** Python computes everything and sends ONE composite script that applies every change (cards, pieces, dials, status line, panel enables), verifies inside the same script, and returns the resulting state for the next step.
3. **Bot turn:** at most 1-2 messages per bot action, with all the moves and announcements of that action in a single script.
4. **Instant local feedback:** the panel script shows "Procesando..." and greys out the buttons as soon as it is clicked, with no round trip.
5. Target: ~0.5-1 s per human button; ~1 s per bot action.

## 2. Setup buttons and restarting
- "Mulligan" and "Listo" are only visible during setup.
- During the game, a "Reiniciar partida" button replaces them; a double press confirms it, within 3 s.
- Restarting:
  - returns hands, discards and face-down cards to their decks and shuffles them (both sides);
  - full HP on every dial; destiny back to 0;
  - takes every piece off the board (to `dead_spot` / the side);
  - deletes the saved state and goes back to the draw, the mulligan and placement.

## 3. New panel (layout approved by Iván)
```
┌─ TURNO ─────────────────────────┐
│ Tu turno · 2 acciones · Revelar │  ← status line: what the bot expects now
│ [ Maniobra ]      [ Plan ]      │
│ [Ataca Hellboy] [Ataca Lobster] │
│ Objetivo: [Medusa][H1][H2][H3]  │
│ [ Revelar ]      [ Cancelar ]   │
│ [        Fin de acción        ] │
└─────────────────────────────────┘
┌─ VIDA ──────────┐  ┌─ PARTIDA ───────────┐
│ Medusa  [-][+][x]│  │ [Mulligan] [Listo]  │ ← setup only
│ Harpy 1 [-][+][x]│  │ [Reiniciar partida] │ ← during the game
│ ...              │  └─────────────────────┘
└─────────────────┘
```
- Wider, taller buttons in a grid; a TURNO / VIDA / PARTIDA section on each.
- A status line that updates live (`UI.setAttribute`/`setValue` on the bot's own object, never Global).
- Buttons that cannot be used are greyed out (`interactable=false`): Revelar with no combat, targets out of range, setup buttons during the game, and so on.
- Keep the orientation (rotation 0 0 270) and white text; the scale may change.
