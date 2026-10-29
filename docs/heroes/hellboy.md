# Hellboy (Hellboy + Lobster Johnson)

Datos y especificacion para que el bot pueda llevar a Hellboy (F07, caja Hellboy). Hecho el 2026-10-28 en la rama `data/hellboy`, solo datos: ni `sparring/` ni `features.json` cambian.

## Ficheros
- `data/heroes/overlay/hellboy.json`: hoja de CardID verificada (ya existia; se verifica, no se rehace).
- `data/heroes/hellboy.json`: HeroDef regenerado con `tools/import_hero.py hellboy`; `--all --check` pasa.
- `data/heroes/effects/hellboy.json`: habilidad, 13 cartas con ops, primitivas extendidas, 1 plugin, informacion oculta, objetos de la mesa y preguntas abiertas.
- `tests/test_hero_hellboy_data.py`: 6 tests sin FakeTTS ni sockets.

## El heroe en dos lineas
Hellboy, 18 PV, movimiento 2, cuerpo a cuerpo; Lobster Johnson, 6 PV, movimiento 2, a distancia, 1 miniatura que empieza en el tablero (nada en reserva). Mazo de 30 con 11 cartas de destino (corona). La forma no es un estado: con 5 o menos destinos en el descarte es OCCULT DETECTIVE (si empieza el turno en la salida rival, puede robar 2), con 6 o mas es ANUNG UN RAMA (al empezar el turno descarta 1 y mueve a Hellboy hasta el BOOST de la descartada; +2 a los ataques de Hellboy).

## Verificacion de la hoja (carta a carta)
Fuente: FaceURL del CustomDeck 197 del mazo `00dc9a` del save del torneo (las 30 cartas sueltas llevan la clave 187 con las mismas imagenes; 19600 es la carta de personaje, CustomDeck 196). Las 30 posiciones de la hoja 8x4 coinciden con el overlay en titulo, copias impresas (x1, x4, x1, x3, x2, x2, x3, x3, x2, x3, x2, x2, x2), valor, boost, tipo, luchador y corona de destino. Total 30; destinos 11 (Excalibur 1, Right Hand of Doom 4, Confront 2, On Earth 2, Crown of Flame 2). Pancakes! NO es destiny.

## Discrepancias (manda la carta real)
Solo de texto; ninguna cambia valores ni copias:
- Second Shot: la carta dice "You may BOOST this card"; unmatched-memory, "this attack".
- Confront Any Demon or God: "choose a card for them to discard"; unmatched-memory, "choose 1 card" (y un espacio inicial sobrante en `effectAfter`).
- Pancakes!: "Choose two different effects"; unmatched-memory, "Chose".
- unmatched-memory no trae restricciones de luchador ni la etiqueta de destino (ya se sabia): salen de la hoja.
No se corrige unmatched-memory (solo lectura) y, a proposito, tampoco se sobreescribe el texto en el HeroDef: el importador admite `"text"` en una entrada de la hoja del overlay (convencion de la rama data/liz-sherman: `"text": entry.get("text") or card_text(src)`), pero usarla aqui cambiaria el mazo dorado de `tests/golden/decks.json` (compara `text`) y rompería `combat.can_boost`, que reconoce Second Shot por "boost this attack". Cuando el DSL sustituya a esos atajos, las tres redacciones se corrigen con esa misma clave `text` sin tocar nada mas.

## Decisiones
1. Ninguna op nueva. Todo cabe con el vocabulario comun y dos convenciones de argumentos declaradas en `primitives_needed`: `bind`/`ref` (Second Shot suma el boost de la carta descartada; ANUNG UN RAMA mueve hasta el boost de la descartada; On Earth pone su valor al contador destiny) y `options` con `label` en `choose_n` (Posthumous Power elige 1 de 3, Pancakes! 2 distintas de 3).
2. `move` con `amount` es siempre "hasta N" (0 incluido), como en el reglamento; no hay movimientos obligatorios en Hellboy.
3. El dano lleva `source: effect|combat` para que el escudo de Planned Recklessness (`status immune_to_effect_damage` hasta fin del turno en curso) pare solo el de efectos. Es lo que ya hace `Game.effect_shield`.
4. Las formas no se "ponen": se consultan con la condicion `form_is`. El motor las recalcula desde el descarte; Pancakes! puede bajar el contador y devolver a Hellboy a OCCULT DETECTIVE (palanca de forma, no solo reciclaje).
5. El unico plugin, `hellboy:form_change_on_table`, no es una regla: es la coreografia de mesa cuando el bot lleva a Hellboy y cruza el umbral (regla de Ivan: cambia el la miniatura, gira la ficha al lado rojo y hace ping en las dos).
6. `start_on_board`/`reserve` se anaden al ayudante en el overlay; el importador propaga las claves y `parse_hero` las ignora, asi que el motor no cambia.

## Objetos del save para el cambio de forma
Todo dentro de la bolsa `3efeee` "Hellboy" > bolsa `c592d8`:
- Ficha de habilidad: `1644a3` (Custom_Token, escala 0.5) con un hijo `30d50e` pegado boca contra boca. Cara de `1644a3` = ANUNG UN RAMA (roja); cara de `30d50e` = OCCULT DETECTIVE (azul). Girar `1644a3` cambia la cara visible. En el save tiene rotZ 180, que por la geometria del hijo deja la cara azul (inicio) arriba: rotZ 180 = azul, rotZ 0 = roja. Confirmar en vivo.
- Miniatura de Hellboy: `f9789a` ("Hellboy", OCCULT DETECTIVE) con `States {2: e6f06e}` ("Anung Un Rama"). `setState(2)` convierte `f9789a` en `e6f06e` en la misma posicion; `setState(1)` vuelve. `config/partida.json` ya lista los dos GUID en `pieces.hellboy`.
- Lobster Johnson: `e33604` (Custom_Token). Diales: `046660` Hellboy (18), `18c384` Lobster (6), `e17c66` Destiny Dial (el bot ya lo ajusta).
- Secuencia propuesta: anunciar, setState de la miniatura, flip de la ficha solo si no muestra ya la cara nueva (mirar rotZ), ping sobre la ficha y ~1 s despues sobre la miniatura (dos pings seguidos se pisan; `lua._ping_lua` ya espera 1 s), dial de destinos. Todo en `pcall`.

## Informacion oculta (regla de Ivan)
- Confront Any Demon or God es la unica carta de Hellboy que mira la mano rival. El bot la lee SOLO al resolver ese AFTER tras perder el combate, elige la carta a descartar, guarda el resto como KnownHand y la descuenta a medida que el humano juega, descarta o devuelve al mazo; lo que robe despues es desconocido. Si la juega el humano y pierde, el bot revela su mano y el humano elige por botones.
- Glimpse Of Hell jugada por el humano: una carta vista puede haber vuelto al mazo boca abajo, asi que las vistas se degradan a "posible", no certeza.
- Crown of Flame jugada por el humano: KnownHand vacia + 2 desconocidas. Pancakes!: las devueltas al fondo del mazo son publicas para los dos.

## Cobertura
13/13 titulos (30/30 cartas) con entrada: 11 titulos con ops (28 cartas), 2 sin texto y sin ops (Excalibur, Service Pistol). 0 cartas con plugin. Habilidad entera con ops (2 disparadores + 1 pasiva). Vocabulario usado: draw, discard, move, damage, heal, if, optional, for_each, choose_n, modify_value, status, cancel_effects, look_hand, return_to_deck, gain_action.

## Decisiones de Ivan (28/10)

- Right Hand Of Doom: OCCULT DETECTIVE se evalua antes de que la propia carta llegue al descarte.
- Pancakes!: las opciones elegidas se resuelven en el orden impreso.
- cambio de forma con el bot: cambia miniatura y ficha y hace ping sobre las dos.
- elecciones del humano (Confront, Posthumous Power, Pancakes!) por botones del panel que SOLO aparecen cuando se juega la carta; mientras tanto no se muestran (ni en gris).
- (29/10, E2) Habilidad de inicio de turno del humano (robo de OCCULT DETECTIVE en la salida rival, descarte y movimiento de ANUNG UN RAMA): la hace el humano en la mesa; el panel la anuncia y BLOQUEA el resto de botones (solo Fin de accion y los de PV) hasta que pulsa Fin de accion; se reanuda desde un guardado.
- (29/10, E2) Zona ONGOING propia debajo de la zona de combate (`human_ongoing_spot` / `bot_ongoing_spot`): el humano deja ahi su plan ONGOING y la sesion lo reconoce ahi; cuando caduca el chat pide pasarlo al descarte. El bot pone el suyo boca arriba ahi y lo manda a su descarte al caducar. Sin esos valores en la configuracion se reconoce en el descarte (aviso).
- (29/10, E2) And Upon His Brow Is Set A Crown Of Flame: Fin de accion espera a que los descartes de la mano esten en la pila (confirmado).

## Preguntas abiertas

- Ficha de habilidad 1644a3: la lectura 'rotZ 180 = OCCULT DETECTIVE arriba' sale de que el hijo 30d50e (cara azul) esta pegado girado 180 grados; confirmar en vivo con --read-only antes de que el bot la gire solo.
- Confront jugado por el humano y perdido: el bot revela su mano boca arriba con ping, por analogia con la respuesta 4 de Ivan (Every Possible Angle); el humano elige la carta con botones. Confirmar.

## Evidencia
```
.venv\Scripts\python tools\import_hero.py hellboy          -> escrito
.venv\Scripts\python tools\import_hero.py --all --check    -> 0
.venv\Scripts\python -m pytest tests\test_hero_hellboy_data.py tests\test_heroes.py -q   -> 16 passed
```
Mutacion de control: con una op fuera del vocabulario y una copia cambiada en el fichero de efectos, el test falla (`assert 3 == 4` en Right Hand Of Doom; op desconocida en el test de vocabulario).
