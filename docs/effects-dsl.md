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
| `card_discarded` | `player`, `from: [hand, deck]`, `cause_not: hand_limit`?, `filter: CardFilter` | `$card` |
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
| `set_value` | `card` y `amount` o `ignore: true` | | `amount`: el valor impreso pasa a ser N (los bonos siguen); `ignore: true`: "ignore its value", el valor total pasa a 0 (Incinerate) |
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
  options in printed order, not choice order; `defeated` = dead on the board: `died_at` set, or a fighter the
  HeroDef starts on the board (it was never in reserve; a Harpy dead in a save older than `died_at`), reserve fighters
  are not defeated (`select.defeated`); `moved_this_turn` reads `fx.turn_start_pos`; several fighters whose
  destinations are asked one by one (`move` with `pick: all`, placements) go in fighter id order, sidekicks before
  the hero, each seeing where the previous ones ended (the order Winged Frenzy has always used).

### C4 hidden information (`effects/ops_info.py`, `KnownHand` in `state.py`)

- `look_hand` is the only caller of `Game.observe_hand` (a test scans the source). `KnownHand` of player P is what P knows about P's RIVAL: `seen` (certain), `possible` with `possible_lo`..`possible_hi` (seen once, maybe gone face down) and `top_of_deck` (known prefix of the rival deck, top first). `KnownHand.cards` never reads the rival hand or deck: every route that takes a card out of a hand must call `Game.card_left_hand` (the old hand/deck membership check was a read of the human hand and was dropped).
- A card leaving a hand in plain sight (played, discarded, picked by the rival) is forgotten exactly. A card returned face down by its owner (Glimpse Of Hell, Pyrotechnics, Pact Of Secrecy) degrades the rival's `seen` to `possible`: `lo = certain - removed`, `hi = min(seen, hand size after)`. Pact Of Secrecy over a fully seen hand of 5 leaves exactly 2 possible of 5.
- Deck top: a rival pick put on top (Every Possible Angle), a public discard pile card put on top, or a `look_deck` of the rival deck sets `top_of_deck`; a shuffle or a hidden card on top clears it; `Game.draw` moves the known top card into `seen` and clears the prefix if an unknown card came out first.
- `return_to_deck`: `order` lists are top first (`top`: first goes on top; `bottom`: last is the very bottom); `shuffle` uses a permutation memoized in the run, so a rerun never reshuffles. `search_deck` takes from the top `look` cards, `rest` goes bottom (random: memoized permutation; ordered: asked) or top (ordered) or the whole deck is shuffled.
- `reveal` of a card in a hand adds it to the viewer's `seen`; of the deck top sets `top_of_deck`; of a card played face down in combat (attack_card) records it in `run.flags["revealed"][viewer]`.
- Choosing among the RIVAL's hand cards (`ChoiceRequest.extra["of"]` is the hand owner): `ControllerChooser` never shows the options to the controller; it picks the most valuable card of those in its `KnownHand` and, if short, fills by position with the game rng, never by identity. Own-hand discards and returns keep going through `choose_discard`; own deck/discard picks (search, recover) rank by card worth.
- Search: `Knowledge.from_game(game, observer)` is a frozen snapshot of the observer's `KnownHand` (single source of truth). `determinize` keeps the seen cards in the hand, puts the known top at the top of the deck and draws between `lo` and `hi` of the possible cards into the hand.
- Live session routes (`Session._trim_virtual_hand`): when the real human hand has fewer cards than the virtual one (Glimpse Of Hell or Pyrotechnics on the table, a waived hand limit) the model drops unseen cards first; only if a seen card must go does `KnownHand.degrade` run. A blind draw raises `possible_hi` by one without looking at the card. Ivan's ruling: a burning card discarded for the end-of-turn hand limit stays in the discard (no Wildfire return, no leniency in `_discard_done`).

## 12. Events, triggers and the ONGOING slot (C3, `effects/events.py`, `effects/ongoing.py`)

- Only for heroes in `fx.dsl_heroes`. `EffectState.emit(name, *args)` and `EffectState.on_damage(...)` call
  `events.dispatch`: bookkeeping (`fx.attacked`, `fx.turn_start_pos`, `fx.taken` = actions spent, all reset at
  `start_of_turn`), then `until` expiry of the ongoing cards in play, then triggers (the player whose turn it is
  first; ability triggers before the ongoing card's). Expiry first means Fight Or Flight lapses before the
  Wildfire discard of the same start of turn.
- Trigger decisions go to `fx.choosers` (default: the bots' controllers); a run a chooser pauses is parked in
  `fx.parked` (not persisted until E1).
- Damage events come from `Game.damage(fighter, n, source, by=None)`: `damage_taken` always, and for
  `source == "combat"` also `combat_damage_dealt` by `by` (default: the last fighter in `fx.attacked`). The events are
  raised right after the hp drop, before the fighter is marked defeated. "Baba takes 2+ combat damage" is one
  `Game.damage` call, i.e. one combat; damage redirected to Koschei hits Koschei, not her.
- `card_discarded` carries the zone (`hand`, `deck`). `Game.discard_card(..., played=True)` (a scheme being played)
  raises no event: playing a card is not discarding it (so Wildfire does not bounce Searing Clarity back).
- Hellboy has two modes. Flag off: the wrappers `Game.hellboy_detective_draw` / `hellboy_anung_start` drive him (session,
  adapter, script) and the dispatcher does nothing. `'hellboy'` in `dsl_heroes` (D1): the dispatcher runs his triggers
  `detective_draw` / `anung_discard_move` at `begin_turn`, and the wrappers become no-ops (`False` / return), so nothing
  fires twice. `medusa_gaze` stays in `DRIVEN_BY_THE_ENGINE`: the AI, the session and the search decide when it
  fires and on whom and run it through `Game.use_ability` (section 15). `events.run_trigger` runs a trigger on
  request; tests pin that both modes give the same state.
- Turn bookkeeping (`fx.attacked`, `fx.turn_start_pos`, `fx.taken`) is recorded only when an interpreted hero's
  effects file reads it (`events.tracked`: `attacked_this_turn` / `combat_damage_dealt`, `moved_this_turn`,
  `actions_taken_this_turn` / `no_attack_as_first_action`), so a game of heroes that never ask saves like before.
- `card_discarded` carries `cause`; `Game.end_turn`'s hand-limit discard uses `cause="hand_limit"` and Wildfire's
  `cause_not: hand_limit` leaves such a burning card in the discard pile (Ivan, 28/10).
- `no_attack_as_first_action` (Pact Of Freedom) is enforced in `Game.can_attack` / `Game.attack` through `fx.may_attack`
  (`game.turn == player and fx.taken == 0`); the human side is blocked by the panel in E1.
- `fx.parked` is persisted inside `fx` (`parked`) and the session resumes those runs at the panel (section 14).
- ONGOING slot: `fx.ongoing[player]` = `{"card_id"}` (DSL card) or `{"card_id": None, "bonus", "label"}` (the bonus
  `Game.add_combat_bonus` has always stored; saved in the old `combat_bonus` key). `Game.combat_bonus*` are views
  over it. `ongoing.resolve_scheme` plays a DSL scheme: the player's active ONGOING is replaced BEFORE the new
  card's ops run (so the new rules are not yet in force), the card leaves hand/discard while it resolves, then stays in
  play (ONGOING) or goes to the discard pile. Rules and statuses of a card in play are read from the card
  (`ongoing.active_modifiers`, `rules`, `rule_total`), never copied.
- Wired rules: `no_attack_as_first_action`, `max_hand_size` (`Game.end_turn` via `fx.hand_limit`), `no_gain_actions` and the `cannot_gain_actions`
  status (`fx.can_gain_actions`). `effect_damage_bonus` is exposed by
  `ongoing.rule_total` for the damage code (C2).
- `put_in_hand` is C4's (`effects/ops_info.py`); Wildfire's return uses it.


## 13. Combat ops and modifiers (C2: `effects/ops_combat.py`, `effects/modifiers.py`, `combat_flow.py`)

- Rules `dsl_immediately` / `dsl_during` / `dsl_after` come after the legacy rules; the legacy rules (feint, planned
  recklessness, On Earth, boosts, `*_after`) step aside for a card whose owner's hero is in `fx.dsl_heroes`. Each run
  lives in `CombatFlow.runs` (`"moment:side"`, finished ones too) and is saved under `flow.to_dict()["dsl"]`, which is
  absent when nothing DSL happened. `PendingChoice.from_dict` accepts `kind="effect"` (key + request).
- Default choosers (`ops_combat.default_choosers`): a bot's controller (`ControllerChooser`); for a controller with
  `human = True` (HumanProxy) a `TableChooser`: it declines every optional (nothing is paid), leaves optional picks
  empty and refuses a forced pick (`NotImplementedError`, needs the panel, E1) - the engine never pays or picks out of
  the human's hand. A bot without its own `choose_effect` decides an optional that costs cards with `worth_paying`: pay
  when the damage avoided is at least 3 per card or would kill the hero (`optional` passes `cost_cards`, `at_stake`
  and `hp` in the request).
- Ivan's ruling (28/10): effects resolve in timing order (IMMEDIATELY before DURING; same timing, the defender first) and
  a value never drops below 0 at EACH step: Flame Lash (1) vs Arcane Dampener (-3) is 0, then its DURING boost +3 makes 3.
- `flow.choosers` (player -> Chooser) overrides that; a `PanelChooser` makes the flow stop with an
  `Await(PendingChoice("effect"))`, answered with `flow.resume(list)`.
- Values: each side keeps a running total (never below 0). `modify_value` adds; `set_value` with a computed amount
  ("the value becomes N": On Earth, Shock And Awe) replaces the PRINTED part and leaves bonuses (Fight Or Flight,
  extras); `set_value` with `ignore: true` ("ignore its value": Incinerate) zeroes the whole total, bonuses too.
- `cancel_effects` marks the side as cancelled (the legacy semantic: what already resolved stays) unless the card is
  `uncancelable`. `may_boost` cards ask a hand BOOST at the end of their DURING, either side; a card without a BOOST
  value is refused. `combat.can_boost/deck_boost` read the data (index by CardID, `modifiers.card_effects`).
- Statuses (`fx.statuses`, op `status`) expire through `fx.emit("start_of_turn" | "end_of_turn" | "after_maneuver",
  player)` (`modifiers.expire_on_event`, before `events.dispatch`). Modifiers of kind `status`, `rule`
  (`effect_damage_bonus`, `no_gain_actions`) and `redirect_damage` are read from `fx.modifiers` (loose ones,
  `modifiers.add_modifier` / `remove_modifiers`) AND from the ONGOING card in play (`modifiers._modifier_entries` over
  `ongoing.active_modifiers`; C3 never copies them), so a Counterhex Shield or a Pact played as a scheme is enforced. `modify_value` modifiers are NOT read here: the ONGOING bonus reaches
  combat through `Game.combat_bonus_parts` (C3 makes it a view of the ONGOING slot).
- Hooks (bodies in modifiers.py): `adjust_damage` (effect damage only: immune statuses, then +N), `can_draw`,
  `can_gain_actions`, `can_force_discard`, `can_move` (also consulted by `Game.legal_moves`). `fx.acting` is the
  player whose op is running (`damage`, `move`, `place`, `swap`, `discard` set it). `None` means no DSL op is running:
  for `adjust_damage` that is an effect of the legacy engine path (Medusa's gaze...), treated as the enemy's; for
  `can_move` it is the player's own maneuver, which is never an enemy effect (legacy-path effects that move enemy
  fighters do not exist). A discard that is the cost of an `optional` is voluntary and never vetoed.
- Known gap: FATEFUL BARGAINS (and any redirect passive) only acts on DSL `damage` ops; Medusa's damage is one since
  C5, effect damage from the legacy path of the other heroes onto Baba is not redirected until D1.
- `cancel_effects` on a CardRef that names a side of the combat (`opponent_card`, `attack_card`, `defense_card`,
  `this`) marks that side cancelled even when no card was played there (a Feint against no defense), the record the
  engine has always kept; a `$var` that resolves to nothing does nothing.
- `redirect_damage`: the op registers the redirection for the combat and it is applied in the DAMAGE phase (a
  non-optional one; an optional combat redirect raises NotImplementedError, it needs a pause inside DAMAGE). Passives
  and ONGOING `redirect_damage` act on effect damage inside the `damage` op, asking the optional ones through the
  chooser of the passive's owner.
- `next_attack_bonus` is consumed by the first attack of that player (`CombatFlow._reveal`).
- Not covered: the `scheme` moment (C3), the `boost` moment of a card used as a boost, `until` events other than
  the turn events for `status` statuses (the ONGOING `until`s are C3's).

## 14. E1 human choice infrastructure (`session_choices.py`, `Session`)

- One pause mechanism. The panel shows exactly one decision of the human at a time, `Session._paused()`, in this
  order: the pending combat stopped inside a card effect (`Pending.flow`, a `CombatFlow` whose `PanelChooser` raised
  `Await(PendingChoice("effect"))`, C2), an effect outside combat (`Session.free_effect`, an `EffectRun`) and the
  ability triggers a chooser parked (`game.fx.parked`, C3), oldest first. `Session.effect_run` is the `EffectRun` of
  that pause; its `awaiting` is the `ChoiceRequest` on `btn_choice_1..6`. Event `CHOICE {"i": 1..6}` answers: a
  single pick answers at once; multi-pick requests toggle options (numbered in click order) plus a Confirm button;
  more than 6 options page with a "Mas" button. The answer goes through `flow.resume(list)` and the session keeps
  driving the flow (`_drive_flow`: the bot's effect decisions through `ControllerChooser`, boosts as the synchronous
  `legacy_chooser` does, the human's boost being the card the table read before) or through `run.resume(list)` and
  `run.run`; the next pause re-shows the buttons, the end closes the combat (`_after_combat`) or the effect.
- Combat: `Game.begin_attack` does what `Game.attack` does before the cards resolve (checks, action, `attacked`
  event, the defense) and returns the `CombatFlow`; the session drives it. At a pause the bot's changes so far
  (moves, a boost to the discard) are projected on the table, so a save taken there matches what `--resume` reads;
  the played cards are held by the flow (in no zone: `read_bot_hand` never puts them back in the hand or the deck).
- `Session.play_effect(run)` is the public entry point E2 calls for the human's cards outside combat (schemes): it
  runs the `EffectRun` with `{bot: ControllerChooser, human: PanelChooser}` and leaves it waiting at the panel.
- Triggers: the session sets `game.fx.choosers` to the same pair, so a trigger that asks the human parks its run
  (`fx.parked`, persisted inside the game's `fx` as `parked`) and the panel surfaces it; answered runs leave the
  list. Search clones copy `fx.choosers` (EffectState.copy): D1/D2 must give the search its own choosers before a
  DSL hero of the human has triggers, or those runs park inside the clones.
- Rollback: every engine step that may stop halfway inside an effect (`_resolve_combat`, a `CHOICE` answer,
  `play_effect`) runs under a snapshot of the whole save (`Session.to_dict`); a `RuleError` restores it
  (`load_dict`) and says "Accion ilegal", any other exception restores it and propagates. Nothing half-applied
  stays, the action is not spent.
- Save format: `pending.flow` (the `CombatFlow.to_dict()`) and `pending.combat` (what finishing it needs: flip,
  human_guid, bot_seen, alive_before, before, boost) only while a combat is stopped; top-level `effect` only while a
  free-standing effect waits; `look_granted` only when true; `game.fx.parked` only when non-empty. Old saves load
  unchanged and the golden saves are byte-identical. `--resume` repeats the prompt and the buttons.
- UX rules (Ivan): choice buttons are hidden (`active=false`, not greyed) unless a choice is pending; while one is
  pending every other action button is greyed and the event is refused. `btn_look` is hidden and refused unless a
  card granted the look: `session_choices.grants_look` reads the card's DSL effects (any moment with a `look_hand`
  on the opponent: Confront Any Demon or God, Advanced Psychometry, Every Possible Angle, Remove A Painful Memory)
  when the human's combat card resolves or their scheme is recognized; the conditions around the op are not
  evaluated. The grant ends when the look is taken (`_look_hand`), when the human starts another action or when
  the bot's turn goes on; a grant given by the human's last action holds the end of the turn one button.
- Restrictions on the human (`session_choices.RESTRICTIONS`, `fx_query`: a missing query allows the action):
  `may_attack` hides the attack buttons and refuses the event (Pact Of Freedom); `can_draw` makes the Maneuver skip
  the draw and `can_gain_actions` makes a scheme's actions not count (Cold Iron And Holy Water), both said in the
  chat; a fighter `can_move` refuses keeps the engine's space when the table moves it. Each reason is told once
  while it lasts.
- `lua.set_panel(..., labels={id: text})` sets button texts through `panel.UI.setValue(id, text)`; to be verified
  live (relies on `UI.setValue` working on a Button).

## 15. Medusa on the interpreter (C5)

- `effects/state.py`: `INTERPRETED_HEROES = {"medusa"}`. `Game.__init__` derives `fx.dsl_heroes` from the heroes in
  play; persist omits the set when it equals that default and fills it on load (an old save of Medusa vs Hellboy
  loads with Medusa interpreted; an explicit choice away from the default, e.g. `set()`, is written as it is). The
  goldens of f4c26ca are byte-identical.
- Decisions stay where they were, the interpreter does the work (`effects/driven.py`). The AI planner, the session
  and the search decide when the gaze fires and on whom (`pick_ability_target`, the search move `("ability", fid)`)
  and which fighter A Momentary Glance hits (`Act.target`); `Game.use_ability(player, "medusa_gaze", target)` and
  `Game.play_scheme(..., target=)` hand those answers to the run as presets (`PresetChooser`: the preset answers
  requests of its kind, the rest go to the normal chooser). A preset that the effect could not pick is a RuleError
  raised before the action is spent (`driven.fighter_options`). D2 replaces the presets by the chooser deciding
  inside the search.
- Winged Frenzy's moves and placement go through the normal choosers: `EffectAI._space` defers an own-piece `move`
  to `MedusaAI.choose_move` (the planned destination, else the kiting/harpy rules) and a dead own piece's placement
  to `choose_placement` (the planned spot), so the controller is called exactly as often and in the same order as
  the legacy engine (the rng is only touched through those calls). The one ruled divergence (Ivan, 28/10): the
  return of a defeated Harpy is mandatory; a `choose_placement` that answers None gets the first free space of
  Medusa's zone. The AIs never answer None, so no golden changed.
- The human's forced discards keep the table route: a `discard` op where the human picks from their own hand goes
  through `Game.force_discard` (HumanProxy owes it, settled at "Fin de accion"), never through a chooser that would
  list the human's cards; a bot's own-hand discard goes through `choose_discard` with the card's title as the reason.
- Deleted: `_medusa_after`, `_optional_move`, `check_scheme`, the Medusa branch of `resolve_scheme`, the flow rules
  `feint` / `second_shot` / `medusa_after`, `Game.medusa_ability`. Verbatim copies live in tests/legacy_medusa.py
  as the oracle of tests/test_medusa_dsl_diff.py (`legacy(monkeypatch)` rebuilds the pre-C5 engine).

## 16. The bot's box hero on the interpreter (D1)

- `effects/state.py`: `BOT_INTERPRETED_HEROES = {hellboy, abe-sapien, baba-yaga, liz-sherman}` are interpreted only
  for the player the bot controls (`default_dsl_heroes(game)` reads `game.bot_player`; `Game.new` sets it after the
  bot is known, persist derives the same default on load). Medusa stays in `INTERPRETED_HEROES` for either side.
  The human's box hero keeps the legacy table path (text in `human_effects`, Horseshoes / On Earth / Flame Lash's
  action applied by `_hellboy_after` / `_liz_after`) until E2, so the goldens of 71e43bb are byte-identical and the
  human's panel path is exactly as E1 left it. An old save of a box bot loads interpreted; an explicit
  `dsl_heroes: []` in a save stays off and the bot's cards are then only announced as unresolved
  (`bot_card_outside_the_interpreter`, the one AFTER rule left for the bot).
- Deleted: `bot_card_after`, `_announce_bot_card`, `text_parts`, `CODED_MOMENTS` (verbatim copies in
  tests/legacy_combat.py). The flow differential of tests/test_combat_flow_diff.py now plays the box heroes on the
  HUMAN side only; the bot's side is pinned by tests/test_d1_bot_cards.py (every combat card of the four heroes,
  state and chat line), not by a byte-identical oracle: where the legacy path was incomplete the behaviour changed
  (bot Flame Lash's bottom-card boost now applied, Out Of Time boosted from the bot's hand on either side,
  Incinerate asked to the rival as a real choice instead of a "tu opcion" note after the damage, every other
  moment applied by the engine instead of "el bot ignora este efecto").
- Boosts: `legacy_chooser` asks the controller of a bot's interpreted card (`choose_combat_boost`) like it did for
  Medusa; `MedusaAI.choose_combat_boost` and the search's `SearchController.choose_combat_boost` value a DEFENSE boost
  by the damage it spares (Out Of Time).
- Narration (`effects/narrate.py`): a run of the bot's box-hero card snapshots the public state when it starts
  (`run.flags["before"]`, JSON-safe, so a pause of the human survives a save) and, when it ends, `run_moment` adds
  one Spanish line to `result.applied` (`<card>: <changes>` or `<card>: sin efecto`): hit points, deaths, returns
  to the board, moves, draws (counted, never named), discards (named: public), public returns to the bot's hand
  (Wildfire, Ward And Prepare), cards put to the deck face down (counted), actions gained, the turn ended, statuses,
  cancellations, value changes, redirections and a look at the human's hand. Medusa's cards stay silent, as C5 left
  them (the C5 oracle compares `applied`).
- `EffectAI`: an optional redirect (FATEFUL BARGAINS) is decided by `hp_change` of both candidates (the blow's
  `amount` travels in the request); losing an own sidekick now costs `KILL_SIDEKICK`, so a lethal blow stays with
  Baba. `ops_core._cost_context` gives the ATTACKER a stake too (the damage the defense blocks, and what the target
  would still have left), so `worth_paying` is the one policy for both sides.
- Perfect Shot: the plugin `abe:perfect_shot` is registered; the prediction belongs to the moment the card is
  played (E3: the bot announces it, the human gets buttons) and is read from `flags["prediction"]` of the
  IMMEDIATELY run; until E3 the bot plays it face down (no +2).
- `PresetChooser` answers the first request of its kind and then steps aside (B.P.R.D. Utility Belt picks twice);
  `driven.fighter_options` skips player-scoped statuses. `EffectState.copy()` never carries `choosers` or `parked`:
  search clones and `blind_clone` decide with their own controllers.
- Search: `adapter._advance` leaves Hellboy's start of turn to the dispatcher when he is interpreted (the bot's
  Hellboy): no `anung` moves are enumerated for a discard the engine already made.

## 17. Schemes and abilities of any interpreted hero in the bots (D2)

- Schemes of a box hero are decided INSIDE the card, by a chooser, while it runs: `Game.play_scheme(..., choosers=)`
  (`driven.preset_choosers(game, owner, by_kind, base)`) hands the run the choosers of the caller; nothing is
  preset. Medusa keeps C5's presets (the planned target of A Momentary Glance, the frenzy policy through
  `SearchController.choose_move`), so her controller-call order and rng are byte-identical
  (tests/test_medusa_dsl_diff.py, goldens unchanged).
- Heuristic (`MedusaAI.scheme_acts` -> `scheme_act`): one act per scheme title of the bot's hand, valued by playing
  the card on a blind clone with EffectAI deciding inside (`EffectAI.scheme_outcome`, the same rules the real play
  uses): `material_delta` (hit points by weight, kills, the ONGOING that enters or leaves both slots) + CARD_VALUE per
  card drawn - keep_value per card given up - CARD_VALUE for the card itself + ACTION_VALUE per action it grants.
  `Act.sim` is the expected state (`apply_expected` returns a clone of it) and a simulated win scores +DEATH
  (`MedusaAI.outcome`; the old code took any finished game as the bot's death, Medusa's expected sims never finish
  a game). The act's kind is `"scheme"`; the session says "El bot juega <title>" like a glance or a frenzy.
- Search (`adapter._scheme_moves`): `("scheme", title, None, variant)` per title of an interpreted hero's hand,
  with `variant` in `SCHEME_VARIANTS = ("greedy", "safe")` when the card's ops ask something (`scheme_variants`:
  a move/place/swap/revive/summon, an optional, a choose_effect, a choose, a search_deck or any selector with a
  `chooser`) and a single `None` line otherwise (Crown Of Flame, Counterhex Shield). At most `SCHEME_MOVES_KEEP = 6`
  scheme moves per node, the safe lines dropped first. `apply` plays the card with `SyntheticChooser(variant)` for
  the mover and `SyntheticChooser("greedy")` for the rival; `IsmctsMedusa.to_act` turns the move into
  `Act("scheme", variant=...)` and `MedusaAI.execute` plays it on the real game with that same chooser for the bot
  (`scheme_choosers`: what the search evaluated) and the rival's usual chooser (its controller, or the panel in a
  session). A hero outside `fx.dsl_heroes` (the human's box hero until E2) still plays no scheme in the search.
- `SyntheticChooser` policies `greedy` / `safe`, each from the answering player's point of view: greedy brings an
  own piece to a strike spot (else nearest to the foes), a rival piece within the own hero's reach, pays costs and
  takes the first options; safe moves an own piece away, a rival piece out of reach, declines costs and takes the
  last options. Both hit the enemy that pays most (kill, hero, weakest), heal who needs it most, give up the
  cheapest cards (`card_worth`) and take the best, and never draw into exhaustion. A rival-hand pick goes through
  `ControllerChooser._from_rival_hand` (only what a look showed), so the live bot never ranks unseen cards; in the
  search the game is determinized, so a chooser there only ever sees the sampled hand (test with `HandSpy`).
- The ONGOING slot is valued once, `ongoing.worth(game, player)` in hit points: +1 per point of value on the
  owner's combat cards (Fight Or Flight), +0.5 per immunity status (Counterhex Shield: 1.5), +0.5 per point of
  effect damage bonus (Pact Of Mortality); rules that bind both players (Pact Of Freedom / Secrecy / Time, Peace's
  trigger) count 0. `EffectAI.evaluate` / `material` add `W_MEDUSA_HP * worth(me) - W_HERO * worth(rival)`;
  the search's `_side_value` adds `EvalWeights.ongoing * worth / hero.max_hp`. Replacing one ONGOING with another
  (`ongoing.enter_play`, one per player) is therefore scored as the trade.
- Abilities: the start-of-turn triggers of the box heroes (Hellboy's detective draw / ANUNG discard and move, Liz's
  Wildfire bottom discard) fire through `events.dispatch` at `Game.begin_turn`, in the simulator's loop, the
  session and inside `adapter._advance` (no hand-coded step; the bot's Hellboy enumerates no `anung` moves). Abe's
  tokens and Baba's pacts are event triggers (`combat_damage_dealt`, `attacked`, `end_of_turn`, `damage_taken`):
  the search now emits `attacked` when an attack card is committed (`apply("attack_card")`, as
  `Game._declare_attack` does), so `attacked_this_turn` (Pact Of Peace) and UNCANNY INTUITION's spend fire inside
  the tree. Decisions of those triggers go to the controllers (`SearchController` in the search, EffectAI live).
- A search clone gets its own rng at `determinize` (a shuffle inside a simulated effect, Pact Of Secrecy, never
  moves the live game's rng).
- Liz (Ivan, 29/10): the bot leaves a burning card at the bottom of its deck when a card lets it (Pyrotechnics:
  `EffectAI._cards` prefers a card of the returning tag for a bottom return, `_order` puts it last, the request
  carries `position`); the optional is accepted because `evaluate` counts a returning card at the bottom as kept
  (`keep_value + BOUNCE_BONUS`). `returning_tag(slug)` reads it from the hero's triggers (a `card_discarded` from
  the deck with a tag filter), nothing is hard-coded. `blind_clone` never leaves a returning card at the bottom of
  the shuffled own deck: the bot does not know its bottom card unless it put it there, so only what a simulated
  effect puts there counts.
- Open: a bot scheme that asks the human something (Pact Of Secrecy's "keep 2" of the human) returns the Await from
  `MedusaAI.execute`; the session does not drive it yet (E2's `Session.play_effect` for the bot side).

## 18. The bot's effects on the real table (D3, `sparring/session_bot_effects.py`)

- Projection by diff: `snapshot(session)` (JSON-safe) is taken before each bot step (a combat, from
  `_resolve_combat`; an action of its turn, in `_bot_continue`; the turn change, in `_turn_change_debt`) and
  `project(session, before)` queues F1 builders for what changed, in the step's one combined script (queue domain
  `fx`, so no read of the session flushes them early), then says it. A combat paused at the panel keeps the snapshot
  in `Pending.combat["fx"]` (saved), so a `--resume` still projects; the turn change keeps it in `fx_unprojected`.
- What is projected: the human's miniatures a bot effect moved or returned (`move_piece` by GUID, one attempt, else
  "muevela tu"); the bot's Hellboy form (`set_state` of the miniature state the table shows, `flip_token` of the
  `ability` token, `ping_objects` of token and miniature; Ivan: ping on both); ability counters that have a token
  in `data/tts` (`take_token_copy` of the source per point gained, `remove_token` of the last copy per point spent,
  GUIDs kept in `Session.token_copies`, saved; `token_spot` in the configuration, else beside the bot's deck); the
  bot's own cards: hand -> deck (`hand_to_deck`, the one builder that takes cards out of the bot's hand zone, at the
  bottom when the engine put them at the tail, else shuffled), discard -> deck (`card_to_deck_bottom` per card at
  the tail, else `shuffle_into_deck` by GUID), discard -> hand (`return_card_to_hand`), and cards the engine took
  from its deck outside a draw (Read The Bones) become draws (`drawn`): the real order of the deck is unknown.
  `fx_in_flight` keeps the reconciliation from re-adopting a card the same script is moving off the pile or hand.
- The human's cards are the human's. A card the engine discarded from their hand by name (Confront lost, Remove A
  Painful Memory) is owed through `pending_discard["cards"]`: "Pon X en tu descarte", `sync_human` keeps it in the
  engine discard until the table shows it, `_discard_done` waits for it. A random discard from their hand is
  theirs to pick (`ops_core._table_settles`: `force_discard`, the usual owe): the virtual hand never names a
  placeholder. Hand -> deck is said only for cards the bot knew (seen, or the known top: Every Possible Angle,
  "Pon X en la parte superior de tu mazo"), the rest is counted; `sync_human` never pads the virtual hand with a
  card known to be on top of the deck unless the deck shrank.
- `look_hand` reads the real hand exactly when the op runs: `Game.hand_reader` is installed by the session
  (`read_human_hand`: one `read_hand` message of the human seat, the virtual hand becomes those cards) and only
  `ops_info._look_hand` calls it; `Game.clone` never carries it. Tripwires: no read of the human seat across a bot
  turn and a combat without a look card; a look is exactly one read.
- A bot scheme that asks the human (Pact Of Secrecy) is parked by `ongoing.resolve_scheme` with
  `run.flags["scheme"]`; `_bot_continue` shows the choice and waits, the answer finishes the card
  (`_finish_bot_scheme`: `finish_scheme`, then the bot's turn goes on). `_bot_cards_in_play` keeps that card, the
  ONGOING in play and the flow's played cards out of the hand the table shows. Placing the bot's ONGOING card on the
  table is still open (D2).
- Narration: every interpreted card of the bot is narrated, Medusa's too (Ivan, 29/10); the C5 oracles compare the
  chat and `applied` without those lines. `narrate.record` writes one line per card: "sin efecto" never repeats
  and never hides a moment that did something.
- Costs: a look adds one message; bot Liz's Wildfire (a discard and a move at the start of her turn) adds one
  before her first action; everything else rides in the step's script.

## 19. The human's box hero on the interpreter, in table mode (E2, `effects/table.py`, `sparring/session_effects.py`)

- `effects/state.py`: `INTERPRETED_HEROES` holds Medusa and the four box heroes for both sides (`BOT_INTERPRETED_HEROES`
  is gone). Old saves load interpreted (the default is derived, never written); an explicit `dsl_heroes` in a save
  is kept. The legacy human path (`human_card_after`, `_hellboy_after`, `_liz_after`, `after_text`) left production:
  verbatim copies live in tests/legacy_medusa.py and the legacy rig (`legacy(monkeypatch, keep=...)`) installs them;
  `keep` leaves the box heroes interpreted so the Medusa twins compare only Medusa. The goldens of E2
  (tests/golden/sim.json, game_save.json) moved because the simulated Hellboy's cards now resolve (Glimpse's draw
  and shuffle, Confront's discard, Right Hand Of Doom's move...); the pre-E2 goldens the legacy engine reproduces are
  frozen under tests/golden/legacy/. The session goldens are byte-identical.
- Table mode is what the engine already knew: the player whose controller decides at the table
  (`Controller.human`, `table.table_player`). A simulation or a search clone has none, so there every card is fully
  resolved by the controllers. In table mode an op that needs what only the human holds leaves a JSON-safe note in
  `run.flags["table"]` instead of acting, and the session says it (`table.lines`, "en la mesa: ..."): a pick out of
  their own hand (`discard` of all / at random / their choice goes through `Game.force_discard` and the owed
  discard; `choose`, `return_to_deck` from the hand are notes), the order of their deck (`search_deck`: Read The
  Bones), the destination of their own miniature when they decide it (`move`, `place`; `revive` / `summon` set the
  fighter alive with a provisional space and note where it goes; the table sync reads the real one). Everything
  else runs in the engine: damage and heals (the dials follow), statuses and rules on the bot, values and cancels,
  draws (counted placeholders, "Robas N: hazlo en la mesa"), the bot's discards the bot chooses, the bot's hand and
  deck moves (projected by `session_bot_effects` as the bot's own are), the bot's pieces the human relocates (space
  buttons; projected like any bot move; a rival's effect that moves the human's piece still runs in the engine, D3).
- The table player's start-of-turn ability triggers (Hellboy's draw / ANUNG discard and move, Wildfire's bottom
  card) are not run by the engine (`table.start_of_turn_is_physical`): they read the real deck or an unknown
  discard, so the session says them and the table sync reconciles (`_announce_human_start`). Their other triggers
  run (Wildfire's return, Abe's tokens, the Pacts' end-of-turn damage) and are narrated to the human through
  `fx.said` ("Tu habilidad: WILDFIRE RETURN: Fireball vuelve a tu mano"), drained at the end of the button.
- Flame Lash: the real bottom card the human puts in the discard (the E1 boost wait) is staged at the bottom of the
  virtual deck (`session_effects.stage_bottom_card`), so the card's own `discard` op takes exactly it (and Wildfire
  returns it when it burns). The narration counts a run's deck discards (`run.flags["deck_discards"]`) apart from
  hand discards without ever reading the human's hand.
- Schemes: `Session._apply_human_scheme` runs the recognized card through `ongoing.resolve_scheme` with the panel
  as the human's chooser (`session_effects.play_scheme`); a pause parks the run (saved: `fx.parked`, with the step's
  snapshots in `flags["step"]`, so `--resume` continues it) and `Session._effect_done` closes the step
  (`session_effects.finish`: narration "Aplico <card>: ...", the ONGOING that entered play, the bot's discards, the
  projection of the bot's side, the dials, the deaths). An ONGOING of the human stays physically on their discard
  pile while in play: `sync_human` never re-adopts the card in play, and the chat says when it leaves play (the
  bot's turn change, or a combat: `session_bot_effects` reports it instead of asking for a discard).
- Narration: every interpreted run is narrated now, the bot's into `result.applied` ("Aplicado: ..."), the other
  player's into `result.human_effects` ("Tu carta: ..."), with the table notes at the end; a card that returns from
  the discard pile to a hand is "vuelve a tu/su mano" for either player. `project(..., cause)` labels what the human
  must do on the table by whose effect it is ("efecto del bot", "efectos del combate", "efecto de <card>").
- Panel: an optional single pick (`min 0, max 1`: "move up to N") answers on the click, "Ninguna" picks none.
  "Cancelar" while a card asks is the answer that does nothing ("No" to an optional, nothing picked when none is
  required); a forced pick cannot be cancelled (the card is played). The FATEFUL BARGAINS prompt names the blow
  ("Koschei recibe el dano (N) en lugar de Baba Yaga?"); it is asked only when the bot's effect damage reaches Baba
  with Koschei in her zone (the passive's condition), also at the bot's turn start (a parked trigger stops
  `_bot_continue` until answered).
- Restrictions: a physical draw under Cold Iron (the hand grew while `fx.can_draw` is false) is warned once and
  counted (the table wins; TTS cannot block a draw). A BOOST 0 card put in the discard during the Maniobra is
  warned (`maneuver_baseline`, saved). `Game.maneuver` checks the boost card and the movers before spending.
- Ivan's answers (29/10): the ONGOING zone (`human_ongoing_spot` / `bot_ongoing_spot`, below the combat zones): the
  human's ONGOING scheme is recognized on their spot (`recognize_scheme`; snapshot `ongoing_human` / `ongoing_bot`,
  builder `read_cards_at`) and owed to the discard pile when it leaves play (`session_bot_effects.left_play`); the
  bot's goes face up on its spot (`place_card_face_up`, projected by diff) and to its discard pile when it leaves
  play (the spot is in the discard scope). Without the spots the discard-pile route stays, with one warning. The
  human's start-of-turn ability (`start_of_turn_ability`) gates the panel: `Session.ability_wait` (saved) hides
  every button but Fin de accion and the hit points and refuses the rest until Fin de accion. Wildfire's return is
  folded into the card's line (`narrate._fold_triggers`: "descartas Fireball (Wildfire la devuelve a tu mano)").
- E3's hook: `session_effects.human_chooser(session)` is the chooser of the human's decisions (the panel); the
  hidden-information cards wrap it. `look_hand` by the human runs in the engine (the human's `KnownHand` of the
  bot); the legacy look button (`_grant_look_for`) is for a hero outside the interpreter.
