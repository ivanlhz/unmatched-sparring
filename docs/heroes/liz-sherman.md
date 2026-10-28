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
1. **Wildfire (sustituido: ya no es plugin, es el disparador `wildfire_return` del evento `card_discarded`)**: cambia el destino de cualquier descarte de ardiente desde mano o mazo, lo dispare quien lo dispare (habilidad, Flame Lash, Fleeting Moments, efectos del rival). Nunca por impulsar: una ardiente no tiene valor de impulso y no se puede usar para impulsar (Ivan, 28/10). No es una op de carta: es un gancho sobre la primitiva `discard`. El disparador de inicio de turno sí va en ops (`discard from deck_bottom` + `if card_has_tag burning`).
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

## Decisiones de Ivan (28/10)

- 'bottom card of your deck' es la carta de mas abajo del mazo (la ultima), no la de arriba que se roba. Es la que usan Wildfire al inicio del turno y Flame Lash.
- mazo vacio al inicio del turno o con Flame Lash: no pasa nada (ni dano ni movimiento; Flame Lash suma 0).
- el dano de Wildfire al inicio del turno es obligatorio si hay objetivo, y solo a UN luchador.
- un efecto que ignore el VALOR IMPRESO no quita el +1 de Fight Or Flight; uno que ignore el VALOR, si.
- con el bot llevando a Liz, el bot gira el fondo del mazo al inicio de su turno.
- Incinerate: el rival puede descartar 2 cartas de la mano, ADEMAS de la carta con la que defiende, para ignorar el valor de Incinerate (queda a 0); si no defendio con carta, descartar 2 tambien vale. Con menos de 2 cartas en mano no puede pagar.
- Burning Barrier: cannot_leave_space bloquea todo movimiento del luchador rival (propio o por efectos); a Liz si la puede mover un efecto. El dano posterior es a cada rival en la zona de Liz.
- una carta sin valor de impulso no se puede usar para impulsar: las ardientes (BOOST 0) nunca se descartan como impulso.
- un solo ONGOING activo POR JUGADOR; jugar otro reemplaza al propio activo (dos Fight Or Flight = +1). Pendiente de codigo: Game.combat_bonus aun acumula.

## Preguntas abiertas

- Orden al inicio del turno de Liz: primero se descarta Fight Or Flight y luego el fondo de Wildfire. Supuesto; no interactuan.

## Fight Or Flight en el motor (ONGOING)
- `Game.combat_bonus[jugador]` guarda (bono, etiqueta) vivos. La sesión lo añade al detectar el plan en el descarte del humano; `resolve_scheme` lo añade si lo juega el bot. Regla de Ivan del 28/10 (un solo ONGOING activo por jugador): `add_combat_bonus` reemplaza al activo y devuelve su etiqueta (la sesión avisa «X reemplaza a Y»); dos Fight Or Flight dan +1. Un guardado viejo con varios bonos carga solo el último. El ONGOING del rival no se toca.
- Impulso (28/10): `cards.can_be_boost(card)` (BOOST > 0) es la regla única. El motor lanza `RuleError` si se impulsa un ataque o una maniobra con una carta sin valor de impulso; la IA y la ISMCTS solo generan impulsos legales; si el humano descarta una de BOOST 0 como impulso, la sesión avisa «X no tiene valor de impulso: no cuenta» y sigue esperando. Excepción: la carta del fondo del mazo de Flame Lash suma lo que valga (0 incluido).
- Suma al valor de toda carta de combate del dueño: ataque en su turno (vía `attack_bonus_parts`, junto a las pasivas del héroe) y defensa en el del rival, también si la carta vale 0, se cancela o es On Earth (se suma tras fijar el valor). Sin carta de defensa no hay valor al que sumar. El «valor extra» del panel es aparte y se suma.
- Caduca en `begin_turn()` del dueño (lo devuelve para avisar). Se guarda en `combat_bonus` del `game` del guardado, solo si hay algo; un guardado viejo sin la clave carga a 0.
- IA: `Model.defense_dist` y `attack_dist` lo leen (es público); la ISMCTS lo ve por `resolve_combat` y `attack_bonus` en la clonación. Si lo juega el bot, el motor lo aplica; la IA de Medusa no lo evalúa para sí misma (no es su carta).
- El descarte físico del plan al caducar lo hace el humano (el chat lo recuerda).
