# Liz Sherman (caja Hellboy)

Datos y especificación de efectos (F07, paso 13). Nada de motor: el intérprete no lee todavía `effects/`.

## Resumen
- Héroe a distancia (RANGED en la carta), 16 de vida, mueve 3. Sin ayudantes ni fichas: la bolsa de Liz en el save del torneo solo trae la miniatura, el dial de vida (0..16) y el mazo. El "melee" que recordaba la memoria del proyecto era el ayudante vacío de unmatched-memory (`name ""`, `hasSidekicks false`), que se ignora.
- Mazo: hoja 199 del save (8x4), `CardID = 19900 + idx`; carta de personaje 19800. Las 30 cartas llevan la banda LIZ SHERMAN (ninguna ANY). Las cartas sueltas del save usan la clave 188 con las mismas imágenes.
- Habilidad WILDFIRE: (a) toda carta ardiente que se descarte desde la mano o el mazo vuelve a la mano; (b) al inicio del turno descarta el fondo del mazo: si es ardiente, 1 de daño a otro luchador en la zona de Liz; si no, Liz mueve hasta 2.

## Cartas ardientes (las 15 del plan)
Son una propiedad impresa: icono de llama junto al título y sin círculo de impulso (BOOST 0). No hay contador ni ficha.

| Carta | Copias | Tipo | Valor | Impulso |
|---|---|---|---|---|
| Incinerate | 1 | ataque | 7 | 0 |
| Fireball | 2 | ataque | 5 | 0 |
| Flame Lash | 3 | ataque | 1 | 0 |
| Burning Barrier | 3 | versátil | 2 | 0 |
| Pyrotechnics | 3 | versátil | 3 | 0 |
| Searing Clarity | 3 | plan | - | 0 |

Las otras 15 (Fleeting Moments x3, B.P.R.D. Training x2, Rekindle x2, Feint x3, Evade x2, Fight Or Flight x3) no son ardientes y sí tienen impulso.

## Ficheros
- `data/heroes/overlay/liz-sherman.json`: hoja de CardID, restricción, etiqueta `burning`, disparador `wildfire_start` y pasiva `wildfire_return` como datos.
- `data/heroes/liz-sherman.json`: generado con `tools/import_hero.py liz-sherman`; `--check --all` pasa.
- `data/heroes/effects/liz-sherman.json`: ops por carta, selectores, extensiones de primitivas, plugins, información oculta y preguntas.
- `tests/test_hero_liz_sherman_data.py`: 4 tests de datos (sin TTS).

## Decisiones
1. **Wildfire sigue siendo plugin (`liz:wildfire`)**: cambia el destino de cualquier descarte de ardiente desde mano o mazo, lo dispare quien lo dispare (habilidad, Flame Lash, Fleeting Moments, impulsar, efectos del rival). No es una op de carta: es un gancho sobre la primitiva `discard`. El disparador de inicio de turno sí va en ops (`discard from deck_bottom` + `if card_has_tag burning`).
2. **`liz:incinerate` no hace falta**: cabe con `optional` (quien elige y paga es el rival) + `modify_value set 0` + atributo de carta `uncancelable` que `cancel_effects` debe respetar. Si el intérprete no admite esas tres extensiones, vuelve a plugin.
3. **La carta real manda**: Fight Or Flight tiene un ONGOING que unmatched-memory no trae. El overlay admite `text` por entrada de la hoja y `tools/import_hero.py` lo prefiere al texto de unmatched-memory (una línea). Es el único cambio fuera de datos y tests.
4. Sin contador: `burning` es etiqueta de carta, no se cuenta en ninguna pila (a diferencia de los destinos de Hellboy).
5. La fila de Liz sale de `test_rest_of_the_hellboy_box_loads_basic_data_but_cannot_deal_a_deck` (ya reparte mazo); lo cubre el test nuevo.

## Discrepancias con unmatched-memory
- Fight Or Flight: falta todo el ONGOING ("Add +1 to the value of your combat cards. Discard this at the start of your next turn."). Corregido vía overlay.
- Incinerate: la carta dice "effects" (plural) donde unmatched-memory dice "effect"; sin consecuencias.
- Evade: `effectAfter` con un espacio inicial en unmatched-memory; sin consecuencias.
- Ayudante vacío con `attack: melee`: ignorado.

## Cobertura de efectos
12 títulos, 12 con ops (100 %), 0 con `plugin` en carta. Un plugin global (`liz:wildfire`). Extensiones de argumentos declaradas sobre ops del vocabulario: `discard from deck_bottom`, `modify_value set / ref`, `status cannot_leave_space`, `if card_has_tag`, `choose_n from/filter/min/max`, `return_to_deck bottom|shuffle`, `optional cost`, `move up_to/through_enemies`, `persistent_scheme until/then`, y el atributo de carta `uncancelable`.

## Información oculta (regla de Iván: solo se mira cuando una carta lo dice)
- Fondo del mazo (habilidad, Flame Lash): nadie lo conoce hasta que se descarta; el bot valora Flame Lash con el mazo restante, salvo lo que él mismo puso con Pyrotechnics (lo recuerda con orden). Barajar (Rekindle, Searing Clarity) borra ese recuerdo.
- Fleeting Moments: el descarte al azar del rival lo saca el humano o un índice uniforme; la carta descartada es pública y se descuenta de KnownHand. Su robo es una carta no vista.
- Incinerate: el rival elige qué 2 descarta; públicas al descartarse.
- Wildfire: la ardiente que vuelve a la mano es pública: pasa a la mano conocida del rival.
- Pyrotechnics: cartas boca abajo al fondo; el bot no lee cuáles fueron cuando el humano lleva a Liz (solo cuentas).

## Preguntas abiertas para Iván
1. Impulsar (descartar la de arriba del mazo) cuenta como descarte desde el mazo para Wildfire? Supuesto: sí (la ardiente suma 0 y vuelve a la mano).
2. Mazo vacío al inicio del turno o con Flame Lash: supuesto que no pasa nada (ni daño ni movimiento, suma 0). Alternativa: tratarlo como "no ardiente" y mover 2.
3. El daño del inicio de turno es obligatorio si hay objetivo (dice "deal", no "may"). Supuesto: obligatorio.
4. Dos Fight Or Flight en juego suman +2? Supuesto: sí.
5. Incinerate ignorado deja el valor a 0 aunque Liz haya impulsado? Supuesto: sí.
6. Burning Barrier bloquea también empujones y cambios de sitio ajenos? Supuesto: bloquea todo movimiento.
7. Con el bot llevando a Liz en TTS, quién gira la carta del fondo cada turno (puente o humano): UX del paso 13.
8. Confirmado por la hoja: 15 ardientes y ninguna con impulso.
