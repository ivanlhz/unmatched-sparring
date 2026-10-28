# DSL de efectos de carta (esquema canonico, version 1)

Especificacion cerrada de `data/heroes/effects/<slug>.json`. La aplica `data/heroes/effects/schema.json`
(JSON Schema) y `tools/validate_effects.py` (schema + comprobaciones semanticas). El interprete
(`sparring/effects/`, paso 4-6 del plan) debe leer SOLO lo que esta aqui; lo que no cabe va a un `plugin`
declarado. Todo lo que el fichero no dice, el motor no lo adivina.

Convenciones del texto: "dueno" (owner) es el jugador que juega la carta o al que pertenece la habilidad;
"rival" (opponent) es el otro jugador. En las habilidades, `this` es el heroe.

## 1. Estructura del fichero

```json
{
 "schema": 1,
 "hero": "<slug>",
 "notes": ["..."],
 "ability": {
  "text": "texto literal de la carta de heroe",
  "counters": {"intuition": {"min": 0, "max": 2, "start": 0}},
  "triggers": [Trigger],
  "passives": [Passive],
  "notes": "..."
 },
 "cards": [Card],
 "plugins": [{"id": "<slug>:<nombre>", "why": "..."}],
 "hidden_info": [{...}],
 "open_questions": ["..."],
 "discrepancies": [{...}],
 "table": {...}
}
```

- `schema`: siempre `1`. Cambiar el esquema sube el numero y el validador rechaza lo que no conoce.
- `hero`: slug igual al de `data/heroes/<slug>.json` (HeroDef). El validador cruza titulos, copias y texto.
- `ability.counters`: contadores de fichas del heroe (fichas de intuicion, rabia, bobinas). Los contadores de
  pila (destiny) siguen en el HeroDef (`counters` + `forms`); desde aqui solo se leen (`{"counter": "destiny"}`).
- `plugins`: todo `{"op": "plugin"}` o `{"kind": "plugin"}` usa un id de esta lista y cada id de la lista se usa.
- `hidden_info`, `open_questions`, `discrepancies`, `table`, `notes`: documentacion libre; el validador solo
  exige los tipos basicos.

### Carta

```json
{
 "title": "Second Shot",
 "copies": 2,
 "text": "DURING COMBAT: You may BOOST this attack.",
 "may_boost": true,
 "uncancelable": false,
 "effects": {"immediately": [], "during": [], "after": [], "scheme": [], "boost": []},
 "ongoing": null,
 "notes": "..."
}
```

- `title`, `copies` y `text` coinciden con el HeroDef (el texto es el de la carta real).
- `may_boost` (opcional, por defecto false): la carta permite impulsar el propio ataque en el DURING sin coste
  ("You may BOOST this attack", "You may BOOST this card"). Es el campo que sustituye a la deteccion por texto de
  `combat.can_boost`. No se repite como op: una carta con `may_boost` no lleva `boost` sobre `this` en `during`, y
  un plan no puede llevarlo. Vale en cualquier combate en que se juegue la carta: Second Shot es solo ataque,
  pero Out Of Time es versatil y jugada en defensa impulsa la defensa (hoy el motor solo contempla el impulso del
  ataque del humano; el interprete debe cubrir los dos lados).
- `uncancelable` (opcional, por defecto false): `cancel_effects` no borra los efectos de esta carta.
- `effects`: los cinco momentos, siempre presentes y siempre listas (vacias si no hay nada):
  - `immediately`, `during`, `after`: combate. Resuelve primero el defensor en cada momento.
  - `scheme`: al jugar un plan (una accion). Solo en cartas de tipo scheme; los otros tres van vacios en planes.
  - `boost`: cuando ESTA carta se descarta como carta de impulso ("BOOSTED WITH" de Houdini).
- `ongoing` (solo planes permanentes): la carta se queda en juego hasta `until`.

```json
"ongoing": {
 "modifiers": [Modifier],
 "triggers": [Trigger],
 "until": Event
}
```

## 2. Gramatica comun

### 2.1 Jugadores (PlayerSel)

Cadena: `owner` | `opponent` | `attacking_player` | `defending_player` | `all` (solo en `reveal.to`) | `$var`.

### 2.2 Luchadores (FighterSel)

Objeto; todo opcional salvo que se indique. Cadena = atajo de `role`.

| campo | valores | significado |
|---|---|---|
| `role` | `this`, `hero`, `opposing`, `attacker`, `defender`, `combatant`, `$var` | `this`: el luchador que juega la carta (en habilidades, el heroe). `hero`: el heroe del dueno. `opposing`: el otro luchador del combate. `combatant`: uno de los dos (elige `chooser`). |
| `side` | `own`, `enemy`, `any` | relativo al dueno. Obligatorio si no hay `role`: "any fighter" se escribe `{"side": "any"}`, nunca `{}` |
| `kind` | `hero`, `sidekick`, `any` (defecto `any`) | |
| `name` | nombre de luchador del HeroDef ("Koschei", "Harpy") | |
| `where` | SpaceSel | donde esta |
| `other` | bool | excluye a `this` (y al luchador de referencia de `where`) |
| `state` | `alive` (defecto), `defeated` | |
| `filter` | `{"attacked_this_turn": bool}` | predicados raros |
| `pick` | `one` (defecto), `all` | `one`: si hay varios, elige `chooser`. `all`: todos, en el orden que diga el que elige |

Ejemplos: "an adjacent fighter" = `{"where": {"adjacent_to": "this"}}`; "each other fighter in your fighter's
zone" = `{"where": {"zone_of": "this"}, "other": true, "pick": "all"}`; "each friendly fighter" =
`{"side": "own", "pick": "all"}`; "a defeated Harpy" = `{"side": "own", "name": "Harpy", "state": "defeated"}`.

Un selector `pick: one` sin candidatos no hace nada (la op se salta); con `pick: all` se aplica a cero.

### 2.3 Espacios (SpaceSel)

Objeto con cualquiera de: `any: true` | `zone_of: FighterRef` | `adjacent_to: FighterRef` | `space_of: FighterRef`
| `nearest_to: FighterRef` | `start_space_of: PlayerSel` | `empty: bool` (defecto true para colocar). FighterRef es
una cadena de `role` (`this`, `hero`, `opposing`, `attacker`, `defender`, `$var`).

### 2.4 Cartas (CardSel y CardRef)

CardRef (cadena): `this` (la carta que se resuelve), `opponent_card`, `attack_card`, `defense_card`, `$var`.

CardSel (objeto):

| campo | valores | significado |
|---|---|---|
| `zone` | `hand`, `discard`, `deck`, `in_play` | obligatorio. `in_play`: planes permanentes en mesa |
| `player` | PlayerSel | obligatorio |
| `filter` | ver abajo | |
| `pick` | `chosen` (defecto), `all`, `random`, `top`, `bottom` | `chosen`: elige `chooser`. `random`: el azar (no existe un chooser "random"). `top`/`bottom`: solo en `deck` (la mano no tiene orden) |
| `amount` | Amount | cuantas; defecto 1. Prohibido con `pick: all`. Si hay menos candidatas, se recorta a las que haya |
| `up_to` | bool (defecto false) | el que elige puede coger menos (0 incluido). Solo con `pick: chosen` |
| `chooser` | PlayerSel (defecto `owner`) | solo con `pick: chosen` |
| `except` | CardRef | fuera las ligadas a ese nombre |

CardFilter: `{"type": ..., "type_not": ..., "tag": ..., "tag_not": ..., "title": ..., "fighter": ...}`.

Informacion oculta: `hand` y `deck` son zonas ocultas. Un CardSel sobre una de ellas con `pick: chosen` y
`chooser` distinto de `player` solo es legal si en la misma lista de ops (o en una que la contiene) hubo antes un
`look_hand` (mano) o un `look_deck`/`search_deck` (mazo) sobre ese jugador. El validador lo comprueba. No hace
falta mirar con `pick: random | top | bottom` (no se elige nada), con `chooser` igual al dueno de la zona, ni para
contar: el test `exists` y el Amount `count_cards` sobre una mano o un mazo ajenos no eligen ni ensenan nada
(Loki y Krang los necesitan). El descarte y `in_play` son publicos.

### 2.5 Cantidades (Amount)

Entero, una ligadura numerica de evento (`"$amount"`, ver 2.10), o uno de estos objetos (todos admiten
`times: int` como multiplicador):

- `{"attr": "boost" | "value", "of": CardRef}`: atributo de una carta ligada (`{"attr": "boost", "of": "$fuel"}`).
- `{"count": FighterSel}` o `{"count_cards": CardSel}`: cuantos cumplen el selector.
- `{"counter": "<nombre>", "player": PlayerSel}`: contador del HeroDef o de `ability.counters` (defecto `owner`).
- `{"stat": ..., "player"|"fighter": ...}` con stat en `hand_size`, `hp`, `max_hp`, `actions_taken_this_turn`,
  `damage_dealt_this_combat`, `damage_taken_this_combat`.

### 2.6 Quien elige (chooser)

`owner` (defecto) | `opponent` | `$var` (ligadura de jugador). Aparece en todo lo que requiere decision (objetivo
entre varios, destino, cuantas, opcion). El azar no es un chooser: se escribe `pick: random` en el CardSel. Cuando
elige el humano el panel pregunta; cuando elige el bot decide su IA.

### 2.7 "Hasta N"

Una sola forma: `amount: N` + `up_to: bool`. `up_to: true` = el que elige decide de 0 a N. En `move` el campo
`up_to` es obligatorio (no hay defecto): todo "move up to N" lleva `true`; un movimiento obligatorio de N exactos,
`false`. En el resto, defecto `false`.

### 2.8 Ligaduras

Una sintaxis: la op que crea la ligadura lleva `"as": "<nombre>"`; despues se referencia como `"$<nombre>"` donde
quepa un CardRef, FighterRef, PlayerSel o Amount, y `{"attr": ..., "of": "$<nombre>"}` para leer un atributo.
Cada ligadura tiene un tipo y solo vale donde se espera ese tipo (el validador lo comprueba):

| crea la ligadura | tipo |
|---|---|
| `discard`, `draw`, `choose`, `look_deck`, `search_deck` | carta(s) |
| `damage` (los luchadores golpeados; Concussion Device) | luchador(es) |
| `for_each` sobre `players` / sobre `fighters` | jugador / luchador |
| eventos (ver 2.10): `$attacker`, `$target`, `$by`, `$to`, `$fighter` / `$card` / `$amount` | luchador / carta / numero |

El ambito es la lista de ops donde se crea, desde la op siguiente, y las anidadas. Nombres reservados (no se
pueden ligar): `this`, `hero`, `opposing`, `attacker`, `defender`, `combatant`, `opponent_card`, `attack_card`,
`defense_card`.

### 2.9 Condiciones (Condition)

Objeto con `test` o un combinador `{"all": [...]}`, `{"any": [...]}`, `{"not": {...}}`.

| test | campos | significado |
|---|---|---|
| `form_is` | `form`, `player`? | la forma del HeroDef |
| `exists` | `fighters: FighterSel` o `cards: CardSel` o `space: SpaceSel` | hay al menos uno |
| `fighter_at` | `fighter: FighterRef`, `space: SpaceSel` | |
| `card` | `card: CardRef`, `filter: CardFilter` | la carta existe y cumple el filtro (sin carta: falso) |
| `combat_result` | `result: won | lost` | para el dueno de la carta. `lost` = no gano |
| `counter` | `name`, `min`?, `max`?, `player`? | |
| `moved_this_turn` | `fighter: FighterRef` | empezo el turno en otro espacio |
| `played_as` | `side: attack | defense` | como se jugo `this` |
| `compare` | `left: Amount`, `op: < <= == >= > !=`, `right: Amount` | |
| `plugin` | `id`, `key` | lo calcula el plugin |

Nunca hay condiciones en cadenas.

### 2.10 Eventos (Event)

`{"event": "<nombre>", ...}`. Sirven para `when` de disparadores, `until` de estados y planes permanentes.

| evento | campos | liga |
|---|---|---|
| `start_of_turn` | `player` (defecto `owner`; `any`) | |
| `end_of_turn` | `player` (defecto `any`) | |
| `after_maneuver` | `player` | |
| `after_attack` | `fighter: FighterSel` | `$attacker`, `$target` |
| `attacked` | `target: FighterSel` | `$attacker`, `$target`, `attack_card` |
| `combat_damage_dealt` | `by: FighterSel` | `$by`, `$to`, `$amount` |
| `damage_taken` | `target: FighterSel`, `damage: effect | combat | any`, `min` | `$target`, `$amount` |
| `card_discarded` | `player`, `from: [hand, deck]`, `filter: CardFilter` | `$card` |
| `card_played` | `player`, `filter` | `$card` |
| `fighter_defeated` | `fighter: FighterSel` | `$fighter` |

Como caducidad (`until`): `{"event": "end_of_turn"}` = el turno en curso, sea de quien sea;
`{"event": "start_of_turn", "player": "owner"}` = el siguiente turno del dueno;
`{"event": "damage_taken", "target": "hero", "damage": "combat", "min": 2}` = los Pactos. El tipo de dano se
llama siempre `damage` (aqui y en `redirect_damage`); `kind` es solo el discriminador de los modificadores.

Trigger: `{"id", "when": Event, "condition"?: Condition, "ops": [Op]}`. Un disparador no tiene `optional`: el
"you may" de una habilidad se escribe con la op `optional` dentro de `ops` (Medusa, OCCULT DETECTIVE), que es la
misma forma que en las cartas.

## 3. Ops (lista cerrada)

Toda op es `{"op": "<nombre>", ...args}`. Argumentos no listados son error.

| op | args obligatorios | opcionales | notas |
|---|---|---|---|
| `damage` | `target: FighterSel`, `amount` | `chooser`, `as` (liga a los golpeados) | SIEMPRE dano de efecto (lo para `immune_to_effect_damage`, lo sube `effect_damage_bonus`, lo desvia `redirect_damage` kind effect). El dano de combate lo calcula solo el motor. |
| `heal` | `target`, `amount` | `chooser` | no pasa de la vida maxima |
| `set_hp` | `target`, `amount` | `chooser` | fija la vida |
| `draw` | `player`, `amount` | `up_to`, `chooser`, `as` | |
| `discard` | `cards: CardSel | CardRef` | `as` | de la mano, del mazo (top/bottom) o de `in_play` al descarte. Con CardRef descarta exactamente esas |
| `choose` | `cards: CardSel`, `as` | | solo liga, no mueve nada |
| `choose_effect` | `options: [{label, ops}]`, `amount` | `distinct`, `chooser` | elegir EFECTOS; `distinct` prohibe repetir |
| `move` | `target`, `amount`, `up_to` | `through_enemies`, `chooser` | `chooser` decide el destino (defecto `owner`, tambien para luchadores rivales: sustituye al antiguo `push`) |
| `place` | `target`, `where: SpaceSel` | `chooser` | teletransporte |
| `swap` | `target`, `with: FighterSel` | `chooser` | |
| `revive` | `target` (con `state: defeated`), `where`, `hp` | `chooser` | vuelve un luchador abatido |
| `summon` | `name`, `where` | `hp`, `chooser` | saca un ayudante de la reserva (`reserve` del HeroDef); sin reserva no hace nada |
| `cancel_effects` | `card: CardRef` | | respeta `uncancelable` |
| `modify_value` | `card: CardRef`, `amount` | | suma (negativo resta); nunca baja de 0 |
| `set_value` | `card`, `amount` | | fija el valor (tambien 0 = "ignore its value") |
| `boost` | `card: CardRef` | `chooser` | impulsa esa carta ahora (descarta la superior del mazo de su dueno). Para el "may BOOST" gratuito de la propia carta se usa `may_boost` |
| `status` | `name`, `until: Event` y `target: FighterSel` o `player: PlayerSel` | `amount` | ver tabla de estados |
| `counter` | `name` y `delta` o `set` | `player` | se recorta a min/max de `ability.counters` |
| `gain_action` | `amount` | `player` | lo bloquean `cannot_gain_actions` y la regla `no_gain_actions` |
| `end_turn` | | | |
| `look_hand` | `player` | | el dueno ve la mano de `player` ahora (ver 6) |
| `reveal` | `cards: CardSel | CardRef`, `to: PlayerSel` | | ensenar cartas |
| `look_deck` | `player`, `amount`, `as` | `from: top | bottom` | mirar sin mover |
| `search_deck` | `player`, `look: int | "all"`, `take: {amount, up_to?, filter?}`, `to: hand`, `rest: bottom_random | bottom_ordered | top_ordered | shuffle` | `chooser`, `as` | Read The Bones, Prophecy, Lady of the Lake |
| `return_to_deck` | `cards`, `position: top | bottom | shuffle` | `order: PlayerSel` | de mano, descarte o mano rival al mazo de su dueno |
| `put_in_hand` | `cards` | | del descarte o del mazo a la mano de su dueno |
| `redirect_damage` | `from: FighterSel`, `to: FighterSel`, `damage: effect | combat | any` | `condition`, `optional`, `chooser` | en `during`: dura ese combate |
| `optional` | `ops` | `chooser`, `cost: [Op]`, `else: [Op]` | el `chooser` decide; `cost` se paga antes (si no puede, no hay opcion); `else` si rechaza |
| `if` | `condition`, `then` | `else` | |
| `for_each` | `over: {"players": "all"} | {"fighters": FighterSel}`, `as`, `ops` | | orden: el dueno primero; luchadores en el orden que elija su jugador |
| `plugin` | `id` | `args` (objeto libre) | id declarado en `plugins` |

### Estados (`status.name`)

| nombre | ambito | significado |
|---|---|---|
| `immune_to_effect_damage` | fighter | ningun `damage` de efecto, propio o ajeno (Planned Recklessness) |
| `immune_to_enemy_effect_damage` | player | solo efectos del rival (Counterhex Shield) |
| `immune_to_enemy_effect_moves` | player | el rival no mueve ni coloca tus luchadores |
| `immune_to_enemy_forced_discards` | player | |
| `cannot_gain_actions` | player | |
| `cannot_draw` | player | |
| `cannot_leave_space` | fighter | por ningun medio |
| `next_attack_bonus` | player (`amount`) | se consume con el primer ataque propio |

### Modificadores (`ongoing.modifiers` y `ability.passives`)

`{"kind": ..., ...}`; las pasivas llevan ademas `id` y, opcionalmente, `while: Condition`, `optional`, `chooser`.

| kind | args | |
|---|---|---|
| `modify_value` | `cards: {player, type?, fighter?}`, `amount` | +N continuo a las cartas que cumplan (ANUNG +2 a los ataques de Hellboy; Fight Or Flight +1) |
| `rule` | `rule`, `amount`? | `no_attack_as_first_action`, `effect_damage_bonus` (`amount`; no al agotamiento), `max_hand_size` (`amount`), `no_gain_actions` |
| `status` | como la op `status` sin `until` | mientras la carta siga en juego |
| `redirect_damage` | como la op, con `optional` y `chooser` | FATEFUL BARGAINS. Es el unico sitio donde `optional` es un campo y no una op: un modificador no contiene ops que envolver |
| `may_boost` | `fighter: FighterSel` | ese luchador puede impulsar sus ataques (King Arthur) |
| `plugin` | `id` | |

## 4. Momentos y disparadores

- `immediately`, `during`, `after`: ops de combate. El motor resuelve defensor y luego atacante en cada momento;
  `cancel_effects` en IMMEDIATELY vacia los tres momentos de la carta rival (salvo `uncancelable`).
- `scheme`: al jugar el plan. Si la carta tiene `ongoing`, tras las ops se queda en juego: sus `modifiers` valen y
  sus `triggers` saltan hasta `until`; entonces va al descarte. Regla de Ivan (28/10): solo hay un ONGOING
  activo a la vez (uno por jugador); jugar otro reemplaza al activo (va al descarte).
- `boost`: al usar la carta como impulso.
- `ability.triggers` y `ongoing.triggers`: un solo formato (Trigger con `when: Event`). Un disparador optional lo
  decide `chooser`.
- `ability.passives`: modificadores continuos con `while` opcional.

## 5. Dano de efecto y de combate

Solo hay un dano en el DSL (`damage`) y es de efecto. El dano de combate (valor del atacante menos el del
defensor) es del motor, igual que el de agotamiento. Las reglas `effect_damage_bonus`, los estados `immune_*` y
`redirect_damage` distinguen por `kind`. Un `damage` sobre un luchador propio es tan de efecto como sobre el
rival (Horseshoes alcanza a Lobster).

## 6. Informacion oculta (regla de Ivan)

El bot solo lee la mano del humano cuando una carta lo dice, en ese momento. En el DSL eso es `look_hand`:

1. `look_hand` es la unica op que ensena una mano ajena al dueno. Se ejecuta exactamente cuando toca (AFTER tras el
   combate, al jugar el plan...) y nunca antes ni en otra carta.
2. Lo visto se guarda (`Game.observe_hand` -> `KnownHand`) y se descuenta carta a carta cuando sale de la mano
   rival por cualquier via (`Game.card_left_hand`). Lo que el rival robe despues es desconocido. Una carta vista que
   ya salio nunca se da por jugable.
3. Elegir una carta de la mano rival (`pick: chosen` con `chooser` distinto del dueno de la mano) solo es legal
   tras un `look_hand` en el mismo efecto. El validador lo exige.
4. `pick: random` sobre la mano rival no mira nada: el humano (o el puente) saca la carta; el bot, si tiene que
   hacerlo por el rival, elige un indice uniforme sin mirar identidades.
5. `reveal` es la via para lo que se juega boca arriba (ataque de Abe con ficha, Perfect Shot, la carta superior
   del mazo). El bot lee exactamente esas cartas y nada mas.
6. Cuando el humano juega la carta contra el bot, el bot ensena su mano (chat o cartas boca arriba) y el humano
   elige por el panel.
7. Mano propia, mazo propio (`look_deck`, `search_deck`) y descartes son informacion legitima para el bot.

Cada fichero lista en `hidden_info` las cartas que tocan informacion oculta y la regla del bot para cada una.

## 7. Planes permanentes

`ongoing` con `modifiers` (reglas y bonos continuos), `triggers` (eventos mientras sigue en juego) y `until`
(evento que lo descarta). Regla de Ivan (28/10): un solo ONGOING activo a la vez (uno por jugador), el nuevo reemplaza al anterior;
`discard` con `zone: in_play` quita el activo (The Time For Deals Is Done).

## 8. Plugins

`{"op": "plugin", "id": "<fid>:<nombre>"}` o pasiva `{"kind": "plugin", "plugin": "<fid>:<nombre>"}`, con el `fid` del
HeroDef como prefijo (`abe:`, `baba:`, `liz:`, `hellboy:`, `medusa:`). Solo cuando ninguna op lo cubre; el id se
declara en `plugins` con `why`, y todo id declarado se usa. En la caja Hellboy queda uno: `abe:perfect_shot` (decision al jugar la carta y
prediccion comparada despues).

## 9. Lo que no cabe (prueba contra 20 heroes del roster)

Comprobado contra alice, sinbad, bigfoot, king-arthur, sherlock-holmes, dracula, invisible-man, jekyll-hyde,
bloody-mary, robin-hood, beowulf, raptors, the-genie, nikola-tesla, loki, deadpool, squirrel-girl,
ancient-leshen, sun-wukong y dr-sattler. Cabe casi todo: dano, curar, robar, descartar (incluido al azar y del
mazo), mover, colocar, revivir, invocar, cancelar, sumar o fijar valor, estados, contadores (rabia, bobinas,
fichas), reglas de los Pactos, mirar y elegir de la mano rival, buscar en el mazo, devolver al mazo o a la mano,
elegir efectos, opcional con coste (Genie, Beowulf), for_each sobre jugadores y luchadores, condiciones compuestas.

No cabe hoy (queda para una version 2 o para plugin):

1. **Formas que cambian por decision** (Alice BIG/SMALL, Jekyll/Hyde "transform"): las formas del HeroDef se
   recalculan desde un contador. Haria falta una op `set_form` y formas sin contador.
2. **Fichas en el tablero** (fog de Invisible Man, insight de Dr. Sattler): no hay tipo "token en espacio" ni
   selectores `with_token`. Es toda una familia de ops (`place_token`, `move_token`, `remove_tokens`).
3. **Efectos diferidos** ("At the start of your next turn, place X": Vanish, Vanish into murder): no hay op que
   programe ops para un evento futuro. Encajaria como `delay: {until: Event, ops}`.
4. **Valores bloqueados** ("cannot be changed by card effects": Impossible to See, Three Wishes): `set_value` no
   tiene `lock`.
5. **Mezclar el mazo con el descarte al buscar** y "search deck AND discard" (Lady of the Lake): `search_deck`
   mira un solo mazo.
6. **Intercambiar valores o leer el valor impreso del rival en `set_value`** (Loki Freyja's Rescue, Mirror Image,
   Deduce Strategy "change the printed value to its BOOST"): `set_value` admite Amount con `attr` de
   `opponent_card`, asi que Mirror Image y Deduce Strategy caben; el intercambio simultaneo de Loki no.
7. **Predicciones y declaraciones** (Perfect Shot, Elementary y Confirm Suspicion de Sherlock, Holy Mackerel de
   Deadpool): no hay op "declara un valor o un nombre" ni test "acerto"; hoy es plugin por carta. Si se repite en
   mas heroes, en v2 entrarian `predict` + test `predicted`.
8. **Habilidades sobre el rival que no son reglas** (Sherlock "no se pueden cancelar HOLMES y WATSON"): seria
   `uncancelable` por filtro de restriccion de luchador, no por carta. Pequena extension: `uncancelable` como
   pasiva con `cards` filter.
9. **Loki MISCHIEF-MONGER** (jugar una carta a la mano del rival, +1 movimiento por TRICK en manos rivales):
   `card_played` como evento existe, pero "ponerla en la mano del rival en vez del descarte" es un destino nuevo
   para `put_in_hand` (`player: opponent`) y el movimiento extra es un modificador de atributo del luchador
   (`modify_stat: move`), que no existe.
10. **Deadpool**: casi todo es fuera del juego (ruidos, nombres, comida); no se modela.
11. **Prevenir todo el dano de combate** (Bewilderment "Prevent all damage"): no hay `status` de inmunidad al dano
    de combate; se anadiria `immune_to_combat_damage` (fighter).
12. **Efectos que leen "cuantas cartas descarto"** (Dracula Beastform: +1 por carta descartada, cantidad libre):
    `discard` con `up_to` liga las descartadas, y `{"count_cards"...}` cuenta un CardSel, no una ligadura. Haria
    falta `{"count_bound": "$x"}`.

Encontrado por el reviewer en las cajas siguientes (sin implementar; cada punto es una extension acotada de v2):

13. **Dados** (Krang, valores `?`): no hay op `roll` ni valor de carta indeterminado hasta resolver.
14. **Segundo mazo** (Pandora): `zone` solo conoce un mazo por jugador; haria falta `deck: <nombre>` en CardSel.
15. **Doblones y tesoreria** (Blackbeard): un contador compartido o de tablero, no del heroe; `counter` solo
    conoce contadores del dueno.
16. **Resultado de combate en el turno y "primera vez por turno"** (Ali, Raphael, Chupacabra): no hay `stat`
    de combates ganados este turno ni condicion `first_time_this_turn`.
17. **Posturas por evento** (Ali): formas que cambian por decision o por disparador; hace falta `set_form` y
    formas sin contador (mismo hueco que 1).
18. **Alcance de ataque modificado** (Ali Float, Shredder, Krang Missiles): no hay estado ni modificador
    `attack_range` (melee a distancia, o alcance N).
19. **Cancelacion parcial** (Raphael, Donatello): `cancel_effects` borra todo; faltaria `moments: [...]` o
    "cancela solo el AFTER".
20. **"Hasta N luchadores"** (Chupacabra): `pick` es `one` o `all`; faltaria `pick: {"up_to": N}`.
21. **Ongoing permanente sin `until` y zona `removed`** (Donatello): `until` es obligatorio y no existe la
    zona "fuera del juego".
22. **Devolver `this` a la mano** (Bruce Lee, Chupacabra, Raphael): `put_in_hand` con `cards: "this"` mientras la
    carta aun esta en combate; el orden respecto al descarte final no esta definido.
23. **Obligar a jugar una carta y `look_hand` del rival sobre el dueno** (Loki): no hay op `force_play`, y
    `look_hand` solo mira desde el dueno hacia `player`; haria falta `viewer`.
24. **Menores**: condiciones sobre zonas concretas del mapa, stats por turno (acciones, movimientos), sustituir
    la maniobra por otra cosa, Foot Soldiers (ayudantes sin carta), mano inicial distinta de 5.

Lo que si se ha anadido ya por el roster aunque la caja no lo use: `summon`, `set_hp`, `swap`, `look_deck`,
`put_in_hand`, `boost` sobre `opponent_card`, `attacked` / `after_attack` / `card_discarded` / `card_played` como
eventos, `compare` y `stat`, `choose_effect` con `distinct`, el momento `boost`.

## 10. Migracion desde los cuatro ficheros de la caja (28/10/2026)

Equivalencias aplicadas:

| antes | ahora |
|---|---|
| `bind` / `as` + `{"ref": "x.boost"}` / `"$x"` / `"kept"` | `as` + `"$x"` + `{"attr": "boost", "of": "$x"}` |
| `move amount N` (implicito hasta N) / `up_to: N` | `amount: N, up_to: true` |
| `draw up_to: true` / `choose_n min/max` | `amount` + `up_to` |
| `self_player` / `self` / `owner` | `owner` |
| `this_card` / `self_card` / `this` | `this` |
| `status: name` / `name` | `name` |
| `for_each ... ops` / `do` | `over` + `as` + `ops` |
| `optional ops+else` / `then+cost` | `ops` + `cost` + `else` |
| `source: effect` / `kind: effect` / nada | nada: todo `damage` es de efecto |
| `for_each` + `each` / `others_in_hero_zone` | `pick: all` en el selector |
| `self_hero`, `koschei`, `adjacent_fighter`, `enemies_in_hero_zone`... | FighterSel estructurado |
| `persistent_scheme` (3 formas) | `ongoing` en la carta |
| `return_to_deck` (3 formas) | `cards` + `position` |
| `choose_n` con `options` | `choose_effect` |
| `choose_n` con `from` | `choose` o directamente el CardSel de la op que mueve |
| `when: "start_of_turn"` / `"triggers"` / `effect_damage_to_self_hero` / `trigger` en `ongoing` | `triggers` con `when: Event` |
| `recover_from_discard` | `put_in_hand` |
| `push` | `move` con `chooser: owner` |
| `rule` como op | `ongoing.modifiers` kind `rule` |
| `redirect_effect_damage` (HeroDef) / `redirect_damage` | pasiva kind `redirect_damage` |
| `uncancelable: true` | igual (campo de carta) |
| texto "boost this attack" | `may_boost: true` |
| disparador con `optional: true` (Medusa, OCCULT DETECTIVE) | op `optional` dentro de `ops` |
| `discard_random` / `chooser: random` | `pick: "random"` |
| `kind: combat` en `until` | `damage: combat` |
| selector de luchador sin lado (`{"where": ...}`) | `side` obligatorio sin `role` |

Decisiones dudosas de la migracion (ver tambien `notes` de cada fichero):

1. Liz WILDFIRE (devolver la ardiente a la mano) pasa de plugin a disparador `card_discarded` + `put_in_hand`. El
   plugin solo decia eso; si el interprete prefiere un reemplazo del destino, se vuelve a plugin sin tocar el resto.
2. Hellboy `hellboy:form_change_on_table` deja de ser plugin: era coreografia de mesa, no un efecto; queda en
   `table.choreography`.
3. Medusa "A Momentary Glance": `side: any` sin `other` (el motor acepta cualquier luchador vivo que comparta zona
   con Medusa, ella incluida).
4. Medusa "Winged Frenzy": el motor deja al controlador no colocar la Harpia (`choose_placement` -> None); el
   texto la hace obligatoria si hay espacio. El DSL sigue el texto.
5. Medusa "Gaze of Stone": los 8 de dano son de efecto (asi lo hace el motor: `game.damage` por defecto es
   `effect`, y Planned Recklessness lo para).
6. Abe "Secure The Scene": `if` hay agente abatido -> `revive` en la zona de Abe; si no, `place` de un agente vivo en la
   zona de Abe (3 agentes en tablero, reserva 0; decision de Ivan del 28/10).
7. Baba "Deathless": abatido -> `revive` junto a Baba Yaga con 3; vivo -> `place` junto a ella + `set_hp` 3 (decision
   de Ivan del 28/10).
8. Abe "Shock And Awe": `moved_this_turn` sobre `this` (el luchador que la juega), igual que antes.
9. Hellboy "Confront": el descarte lo elige el dueno de la mano vista: `discard` con `cards: {zone: hand, player:
   opponent, chooser: owner}` tras `look_hand` (regla 3 de la seccion 6).
10. Pact Of Secrecy: "shuffle all but 2" = `choose` 2 (`as: keep`) + `return_to_deck` de `{zone: hand, pick: all,
    except: "$keep"}` con `position: shuffle`.
11. Counterhex Shield: tres estados separados (`immune_to_enemy_effect_damage`, `..._moves`, `..._forced_discards`)
    en vez de un estado con lista `blocks`.
12. Abe "Leap Away" y Baba "Foul Journey": `role: combatant` (uno de los dos luchadores del combate, elige el dueno).

## 11. Interpreter (C1, `sparring/effects/`)

- `EffectRun(ops, Ctx(...), label)` executes one ops list. It is re-entrant: frames are `(path, idx, loop)`, bindings
  travel as card ids / fighter ids / player numbers, and `answers` is keyed by `label/op path:ask index`
  (for_each iterations add `@pos`). `to_dict` / `from_dict` round-trip through JSON.
- Ops are atomic: every decision is asked before the first mutation; a paused run (`Await`) has changed nothing and
  only the current op reruns after `resume`. Random picks are memoized in `answers`, so a rerun never rerolls.
- Choosers: `ControllerChooser` (bot, via `Controller.choose_effect`, falling back to `choose_move` /
  `choose_discard` / `choose_placement`), `PanelChooser` (human, always an `Await`), `SyntheticChooser` (search),
  `ScriptedChooser` (tests).
- `PendingChoice` / `Await` are the ones of `combat_flow.py` (imported by `effects/choose.py`); an effect pause is
  `Await(PendingChoice(kind="effect", ..., extra={"key", "request"}))`.
- Ops that later phases implement (`cancel_effects`, `modify_value`, ... `look_hand`, `put_in_hand`) are registered
  stubs raising `NotImplementedError("<op>: <phase>")`. Plugins register with `@plugin("<id>")` /
  `@plugin_condition("<id>")` in `effects/ops_core.py`.
- Decisions taken for the gaps in the spec: `summon` takes a never-placed fighter (`died_at is None`); `move` with `up_to: false` prefers spaces exactly N
  away; `gain_action` for a player whose turn it is not does nothing; `end_turn` ends the CURRENT turn whoever owns the
  card (zeroes `game.turn`'s actions, sets `run.flags["end_turn"] = game.turn`); `choose_effect` resolves the chosen
  options in printed order, not choice order; `defeated` = died on the board (`died_at` set), reserve fighters
  are not defeated; `actions_taken_this_turn` is a stub (`NotImplementedError`, C3); `moved_this_turn` reads `fx.turn_start_pos` (filled by C3).

### C4 hidden information (`effects/ops_info.py`, `KnownHand` in `state.py`)

- `look_hand` is the only caller of `Game.observe_hand` (a test scans the source). `KnownHand` of player P is what P knows about P's RIVAL: `seen` (certain), `possible` with `possible_lo`..`possible_hi` (seen once, maybe gone face down) and `top_of_deck` (known prefix of the rival deck, top first). `KnownHand.cards` never reads the rival hand or deck: every route that takes a card out of a hand must call `Game.card_left_hand` (the old hand/deck membership check was a read of the human hand and was dropped).
- A card leaving a hand in plain sight (played, discarded, picked by the rival) is forgotten exactly. A card returned face down by its owner (Glimpse Of Hell, Pyrotechnics, Pact Of Secrecy) degrades the rival's `seen` to `possible`: `lo = certain - removed`, `hi = min(seen, hand size after)`. Pact Of Secrecy over a fully seen hand of 5 leaves exactly 2 possible of 5.
- Deck top: a rival pick put on top (Every Possible Angle), a public discard pile card put on top, or a `look_deck` of the rival deck sets `top_of_deck`; a shuffle or a hidden card on top clears it; `Game.draw` moves the known top card into `seen` and clears the prefix if an unknown card came out first.
- `return_to_deck`: `order` lists are top first (`top`: first goes on top; `bottom`: last is the very bottom); `shuffle` uses a permutation memoized in the run, so a rerun never reshuffles. `search_deck` takes from the top `look` cards, `rest` goes bottom (random: memoized permutation; ordered: asked) or top (ordered) or the whole deck is shuffled.
- `reveal` of a card in a hand adds it to the viewer's `seen`; of the deck top sets `top_of_deck`; of a card played face down in combat (attack_card) records it in `run.flags["revealed"][viewer]`.
- Choosing among the RIVAL's hand cards (`ChoiceRequest.extra["of"]` is the hand owner): `ControllerChooser` never shows the options to the controller; it picks the most valuable card of those in its `KnownHand` and, if short, fills by position with the game rng, never by identity. Own-hand discards and returns keep going through `choose_discard`; own deck/discard picks (search, recover) rank by card worth.
- Search: `Knowledge.from_game(game, observer)` is a frozen snapshot of the observer's `KnownHand` (single source of truth). `determinize` keeps the seen cards in the hand, puts the known top at the top of the deck and draws between `lo` and `hi` of the possible cards into the hand.
- Live session routes (`Session._trim_virtual_hand`): when the real human hand has fewer cards than the virtual one (Glimpse Of Hell or Pyrotechnics on the table, a waived hand limit) the model drops unseen cards first; only if a seen card must go does `KnownHand.degrade` run. A blind draw raises `possible_hi` by one without looking at the card. Ivan's ruling: a burning card discarded for the end-of-turn hand limit stays in the discard (no Wildfire return, no leniency in `_discard_done`).

### E1 human choice infrastructure (`session_choices.py`, `Session`)

- `Session.play_effect(run)` (public; `_begin_effect` inside handlers) runs an `EffectRun` with `{bot: ControllerChooser, human: PanelChooser}`. When the human is asked, the run is kept in `Pending.effect` (a combat is pending) or `Session.free_effect` (no combat) and the panel shows `btn_choice_1..6`. Event `CHOICE {"i": 1..6}` answers: a single pick answers at once; multi-pick requests toggle options (numbered in click order) plus a Confirm button; more than 6 options page with a "Mas" button. Answering calls `run.resume` and continues; the next pause re-shows the buttons.
- Save format: `pending.effect` (inside the pending dict) or top-level `effect`; both keys are omitted when empty, so old saves load unchanged and the golden saves are byte-identical. `--resume` repeats the prompt and the buttons. Continuing the combat itself after a combat-linked effect (C2 `EffectRun` inside `CombatFlow`) is the caller's job: look at `run.ctx.moment` when `Session._effect_finished` fires.
- UX rules (Ivan): choice buttons are hidden (`active=false`, not greyed) unless a choice is pending. `btn_look` is hidden and refused unless a card granted the look (`Session.grant_look()` / `revoke_look()`, saved as `look_granted` only when true; a look that ends with a discard revokes it). While a choice is pending every other action button is greyed and the event is refused.
- Restrictions on the human (`session_choices.RESTRICTIONS`): each one asks `getattr(game.fx, query, None)(human)`; a missing query allows the action. A forbidden button is hidden (attack: all `att_*`), the chat explains once while it lasts, and the session also raises `RuleError` if the event arrives anyway. `fx.can_draw` false skips the Maneuver card with a chat line.
- `lua.set_panel(..., labels={id: text})` sets button texts through `panel.UI.setValue(id, text)`; to be verified live (relies on `UI.setValue` working on a Button).
