# Baba Yaga (caja Hellboy)

Datos leidos de las cartas reales del save del torneo (hoja 331, 8x4, y carta de personaje 332) el 28/10/2026.
Ficheros: `data/heroes/overlay/baba-yaga.json` (hoja de CardID), `data/heroes/baba-yaga.json` (HeroDef generado),
`data/heroes/effects/baba-yaga.json` (efectos estructurados), `tests/test_hero_baba_yaga_data.py`.

## Resumen

- Baba Yaga: 13 de vida, movimiento 2, a distancia. Standee (Custom_Assetbundle `3de904`).
- Koschei: 1 ayudante, 3 de vida, cuerpo a cuerpo, movimiento 2 (el del heroe). Ficha redonda (Custom_Token `e0c176`).
  Empieza en el tablero (1 en tablero, 0 en reserva), en el espacio de inicio del jugador. Vuelve a la mesa con
  Deathless (junto a Baba Yaga, vida 3) o Pact Of Mortality (en la zona de Baba Yaga, vida 3).
- Habilidad FATEFUL BARGAINS: si comparten zona, el dano de efecto que fuera a recibir Baba Yaga puede recibirlo
  Koschei (opcional). En el overlay es una pasiva `redirect_effect_damage`; el motor aun no la aplica.
- Sin formas ni contadores. CardID = 33100 + idx (DeckIDs del mazo en el save), carta de personaje 33200.
- Mazo: 30 cartas. Baba Yaga 16 (The Time For Deals Is Done x2, Iron Teeth x2, Read The Bones x3, Foul Journey x3,
  Bound In Blood x2, 5 Pactos x1), Koschei 2 (Death's Release), ANY 12 (Remove A Painful Memory x2, Hasten Towards
  Death x2, Out Of Time x2, Deathless x3, Exploit x2).

## Los Pactos (pregunta 4 del plan, resuelta con las cartas)

Cada Pacto tiene efecto inmediato, un parrafo ONGOING y la misma condicion de descarte: "Discard this immediately if
Baba Yaga takes 2 or more combat damage".

| Pacto | Inmediato | ONGOING |
|---|---|---|
| Freedom | Draw 2 cards. Place a hero in any space. | Players cannot attack as their first action each turn. |
| Mortality | Return a defeated fighter to any space in Baba Yaga's zone. Set their health to 3. | Increase all effect damage by 1, except for damage from exhaustion. |
| Peace | Deal 1 damage to each other fighter in Baba Yaga's zone. Gain 1 action. | At the end of each turn, deal 1 damage to each hero that attacked. |
| Secrecy | All players draw up to 2 cards, then shuffle all but 2 cards from their hand into their deck. | Players have a maximum hand size of 3. |
| Time | Each player shuffles up to 2 cards from their discard pile into their deck. | Players cannot gain actions. |

En el DSL: `persistent_scheme` con `ongoing` (ops `rule` o `trigger`) y `until` (2+ de dano de combate a Baba Yaga).
Cuatro titulos (9 cartas) preguntan "if you have an active ongoing scheme" (Iron Teeth, Foul Journey, Remove A
Painful Memory, The Time For Deals Is Done): la condicion es `has_active_scheme`.

## Decisiones

1. card_base 33100 y no 18700: las cartas sueltas del mazo llevan la clave 187 del mod original, pero el motor usa los
   DeckIDs del mazo (como Hellboy con 19700). La identidad real es la FaceURL.
2. FATEFUL BARGAINS y Bound In Blood comparten la primitiva `redirect_damage` (efecto opcional / combate obligatorio):
   dos usos, asi que primitiva y no plugin.
3. El plugin `baba:remove_painful_memory` del plan no hace falta: `look_hand` + `choose_n` (con `bind`) +
   `optional` con rama `else` decidida por el rival. Lo que queda (que carta elegir, descartar o encajar el dano) es IA.
4. Los ONGOING son modificadores globales de reglas, no estados de luchador: primitiva nueva `rule` con cuatro valores
   (no_attack_as_first_action, effect_damage_bonus, max_hand_size, no_gain_actions) y `trigger` end_of_turn para Pact
   Of Peace.
5. Out Of Time pide dos primitivas pequenas, `boost` (impulsar esta carta durante el combate) y `end_turn`.
6. Etiqueta `pact` en las 5 cartas de esquema por si un contador o la IA las quiere distinguir.

## Primitivas nuevas pedidas

`redirect_damage`, `rule`, `trigger`, `boost`, `end_turn`. Ademas argumentos nuevos sobre ops del vocabulario:
`persistent_scheme.ongoing/until`, `optional.else`, `choose_n.from/up_to/bind`, `for_each` sobre jugadores con
`$player`, `draw.up_to`, `discard` con target `active_scheme`. Semantica exacta en `primitives_needed` del fichero de
efectos.

## Cobertura

16/16 titulos (30/30 cartas) con primitivas; 0 plugins. Informacion oculta: Remove A Painful Memory (mano rival),
Read The Bones (propio mazo), Pact Of Secrecy (manos tras el efecto), y los robos de Pact Of Freedom y Exploit; el
protocolo del bot para cada una esta en `hidden_info`.

## Discrepancias con unmatched-memory (manda la carta)

- Deathless: "as close to Baba Yaga as possible" (memory: "Baba Yaha").
- Pact Of Mortality: "Set their health to 3" (memory: "healt").
- Read The Bones: "Randomly put the rest on the bottom" (memory: "put rest").
- Habilidad: "FATEFUL BARGAINS" sin "!" (corregido en el overlay con `ability`).
- Los cinco Pactos: memory solo tiene el efecto inmediato; faltan ONGOING y la condicion de descarte.
- Corregido en el HeroDef: las entradas de la hoja del overlay llevan `text` con el texto real (Read The Bones,
  Deathless y los 5 Pactos) y `tools/import_hero.py` lo prefiere al de memory (`entry.get("text") or card_text(src)`,
  misma convencion que la rama de Liz).

Vida, movimiento, tipo de ataque, valores, impulsos y copias coinciden con las cartas.

## Preguntas abiertas para Ivan

1. Deathless con Koschei vivo: "Summon" lo recoloca junto a Baba Yaga con vida 3 o no hace nada? (modelado: solo si esta derrotado).
2. "Takes 2 or more combat damage": en un mismo combate, no acumulado. Y si Bound In Blood desvia el dano a Koschei, el Pacto sigue. Confirmar.
3. Varios Pactos activos a la vez: sin limite? The Time For Deals Is Done descarta uno a eleccion.
4. Pact Of Secrecy "draw up to 2": cada jugador elige cuantas (0-2)?
5. Pact Of Freedom "Place a hero": vale el heroe rival (si) y no ayudantes.
6. Pact Of Mortality "a defeated fighter": tambien del rival?
7. Iron Teeth y The Time For Deals Is Done pueden danar a Koschei (texto literal). Confirmar.
