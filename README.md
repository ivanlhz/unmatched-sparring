# unmatched-sparring

Bot de sparring para Unmatched en Tabletop Simulator. Fase 1: el bot juega **Medusa** contra un humano con **Hellboy** en B.P.R.D. HQ.

## Piezas

| Modulo | Que hace |
|---|---|
| `sparring/board.py` | Carga `data/maps/*.json` en un grafo (adyacencia simetrica, zonas), movimiento legal y alcance melee/rango |
| `sparring/cards.py` | Mazos de Medusa y Hellboy (CardID 17600+idx / 19700+idx) |
| `sparring/state.py` | `Game`: luchadores, mazos/manos/descartes, acciones, agotamiento, fin de turno, formas de Hellboy |
| `sparring/combat.py` | Combate (IMMEDIATELY, DURING, AFTER; el defensor resuelve primero) y planes. Efectos de Medusa implementados; los de Hellboy los resuelve el humano |
| `sparring/ai_medusa.py` | IA heuristica; la funcion de valoracion esta documentada en la cabecera del modulo |
| `sparring/hellboy_script.py` | Hellboy guionizado, solo para la simulacion |
| `sparring/tts/` | Puente: `client.py` (API de editor externo), `lua.py` (snippets, instantanea y script compuesto), `ui.py` (panel de botones) |
| `sparring/persist.py` | Guardado atomico y recarga del estado de `Game` y `Session` (`--resume`) |
| `sparring/session.py` | Pegamento en vivo: eventos del panel -> llamadas a `Game`, y proyeccion del bot en la mesa |
| `sparring/sim.py` | `python -m sparring.sim --games 100 --seed 0` |

`Controller` (`controller.py`) es la costura: el motor pregunta a quien lleva cada jugador (IA, guion o el humano via puente) las decisiones que no son suyas: defensa, boost, descartes, destinos de movimiento.

## Comandos

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m sparring.sim --games 100 --seed 0
```

## Sesion en vivo (diseno; no probado contra TTS real)

`sparring/session.py` une todo. Configuracion obligatoria (`SessionConfig`): asientos del bot y del humano, GUID de las miniaturas (`pieces`; los nicknames solo salen en los mensajes), posiciones de carta/descarte, GUID del mazo y del descarte del bot y GUID del descarte del humano.

1. El bot crea su objeto `SparringPanel` (`lua.create_panel`) con `obj.UI.setXml`. Nunca toca la UI del Global y nunca envia messageID 0/1; el cliente solo envia Lua generado por los constructores de `tts/lua.py`.
2. La mesa manda. La mano del bot se lee de su asiento al empezar su turno, tras cada robo y antes de elegir defensa; su mazo es el multiconjunto de 30 cartas menos lo visto. Robar es repartir del mazo fisico (`deal_cards`) y descartar es mover cartas al descarte (`discard_cards`); ambos se confirman leyendo la mesa con sondeo acotado (`settle_tries`/`settle_wait` en `SessionConfig`); el robo de la ultima carta del mazo (que TTS convierte en `Card`) se resuelve con `bot_deck_spot`. Si una carta no se puede jugar (`played=false`) la accion se aborta.
3. Del humano solo se conoce su descarte (el motor lo iguala al de la mesa en cada sincronizacion, altas y bajas) y el tamano de su mano (conteo). Nada de lo que decide en secreto se inventa.
4. Botones (llegan como messageID 4):
   - **Ataca Hellboy / Ataca Lobster** y luego **Atacar a X**: el humano elige atacante y objetivo; el bot elige defensa contra ese atacante y la deja boca abajo.
   - **Revelar**: lee las cartas boca abajo (solo cuenta la que es del mazo de Hellboy por CardID), valida las dos y solo entonces gira, resuelve y gasta la accion. Si una carta es ilegal (tipo o restriccion de luchador) el combate sigue pendiente y se explica por que.
   - **Maniobra**: gasta la accion y, con `human_deck_guid` configurado, reparte 1 carta del mazo del humano a su mano (`deal_cards` con el rango de CardID de Hellboy y la identidad de su mazo, en el mismo compuesto que el boton: sin mensajes extra). Solo cuenta cartas, nunca lee cuales tiene. Con el mazo vacio no reparte nada y aplica el agotamiento (`EXHAUST_DAMAGE` a cada luchador del humano, anunciado y con diales). Si el reparto falla dice "Roba tu carta a mano" y no se repite; en la siguiente instantanea se comprueba que la mano subio 1 (descontando lo jugado o descartado). Sin `human_deck_guid` solo dice "robas 1". Los demas robos del humano (salida rival, Crown...) no se resuelven solos, asi que siguen siendo a mano.
   - **Plan**: gasta la accion; el humano actua en la mesa.
   - **Fin de accion**: sincroniza posiciones y descarte; es el unico paso tras un combate (el humano resuelve los efectos de despues del combate) y tambien resuelve descartes pendientes (Clutching Claws, Hiss, limite de mano) antes de seguir o pasar al bot.
   - **Cancelar ataque**: si la colocacion de la carta del bot dio timeout, primero se resuelve (`_recover_placing`) y la carta que aterrizo se devuelve a su mano; sale de un ataque del humano pendiente (p. ej. sin carta legal): devuelve la carta boca abajo del bot a su mano (`return_card_to_hand`), limpia el pendiente y no gasta la accion. Al abrir el ataque se comprueba en la mano real del humano (solo validacion, nunca alimenta al motor) que el atacante tenga alguna carta de ataque legal.
   - Una carta de destino que falta en el descarte de la mesa baja el contador al verla ausente en dos botones seguidos, o ya en el primero si el mazo de robo crecio justo en esas cartas ("Destinos de Hellboy: 3 (antes 4)."). La forma sigue a la cuenta: con menos de 6 destinos Hellboy vuelve a OCCULT DETECTIVE (no hay regla de forma permanente en el motor ni en unmatched-memory).
   - **Valor**: bonificador numerico para lo que el motor no calcula del lado de Hellboy.
5. Todo movimiento de piezas del bot decidido por el motor (maniobra, Dash, Hounds...) se proyecta con `move_piece` (por GUID, comprobando `moved`).
6. Al empezar el turno del humano el bot anuncia el robo de 2 (DETECTIVE en salida rival) o el descarte obligatorio y movimiento de ANUNG UN RAMA; los aplica el humano y el bot los aprende al sincronizar.

## Jugar en vivo (F05; solo verificado contra FakeTTS)

```powershell
# 1) primera prueba: solo leer la mesa, no cambia nada (informe en la terminal)
uv run python -m sparring.play --config config\partida.json --read-only
# 2) jugar: crea el panel en un objeto propio y atiende los botones (Ctrl+C para salir)
uv run python -m sparring.play --config config\partida.json --first human
# 3) reanudar tras un cierre o una recarga de TTS (el estado se guarda tras cada boton y en los puntos de control del turno del bot en estado\sesion.json)
uv run python -m sparring.play --config config\partida.json --resume
```

`config\partida.json` lleva los valores leidos de la mesa real (asientos, zonas de descarte, mazos, puntos de carta) y los GUID de las 6 miniaturas (`pieces`) y de los 3 diales de vida (`dials`); lo que sea `"TODO"` se rellena a mano tras `--read-only` (sin ello no se puede jugar). `--send-port`/`--listen-port` permiten usar puertos distintos de 39999/39998 (los tests usan efimeros), `--state` cambia el fichero de guardado. Los mensajes del bot salen por terminal y por `broadcastToAll`.

Protocolo real de TTS: no devuelve valores por el socket (no hay messageID 5). Cada script de `tts/lua.py` se envuelve con un id entero y contesta con `sendExternalMessage({sparring_reply = id, value = ...})` (messageID 4) dentro de `pcall`, de modo que tambien los errores vuelven atribuidos; los messageID 3 sueltos son de otros scripts y solo se registran. Un messageID 1 (recarga) pausa el bucle, vuelve a comprobar los GUID y recrea el panel.

Al arrancar (nunca en --read-only) el bot dibuja en el suelo, con lineas vectoriales de su propio panel y etiquetas 3DText propias (idempotente; se borran al salir), los rectangulos DESCARTE HELLBOY, DESCARTE MEDUSA, COMBATE HELLBOY y COMBATE MEDUSA; nunca toca el Global.

Panel: ademas de los botones de combate, hay una fila por luchador (ambos bandos) con -1 / +1 / Retirar para el dano o curacion de efectos de carta que el motor no ve, y Deshacer fin de partida para corregir una victoria falsa.

Descarte: el bot deja cada carta en el siguiente hueco de una rejilla dentro de su zona (`bot_discard_spot` = origen, `bot_discard_step`, `bot_discard_rows`), saltando el mazo de robo, para que el rival vea el orden de juego. `read_discard` excluye los mazos de robo por GUID y por posicion.

Garantias de la sesion: todo estado pendiente tiene salida (Revelar, Fin de accion, Cancelar ataque) y todo fallo de mesa deja una deuda que el siguiente Fin de accion reintenta antes de que el bot haga nada mas; tras `adopt_after` fallos seguidos, o con Cancelar, el motor adopta lo que muestra la mesa; `bot_deck_spot` es obligatorio.

### Revision 5 (ajustes tras la primera prueba supervisada)

- **Casillas de salida reales**: `start_spaces` en la configuracion (`{"medusa": 30, "hellboy": 3}`); si falta, `start()` las deduce de donde estan los heroes en la mesa. De ellas salen "salida rival: robar 2" y la sugerencia al reponer un luchador.
- **Miniatura con varios GUID**: `pieces` acepta un GUID o una lista (Hellboy cambia de GUID al darle la vuelta a ANUNG UN RAMA: `["f9789a", "e6f06e"]`). Se usa el que exista; tras una recarga de TTS basta con que exista uno de cada grupo. El motor recalcula la forma siempre desde el descarte (6 o mas destinos = ANUNG UN RAMA), no del GUID.
- **Guardado con huella**: `estado\sesion.json` lleva el id de partida, el hash de la configuracion de identidad (asientos, zonas, mazos, GUID, diales, salidas; los ajustes finos como `off_board_dist` no cuentan) y los GUID. `--resume` rechaza un guardado ajeno, antiguo o de otra mesa con un mensaje claro. Los tests no pueden escribir bajo `estado\` (guarda en `tests\conftest.py`) y su `--state` por defecto cae en `tmp_path`.
- **Puntos de control del turno del bot**: se guarda al empezar su turno, tras la habilidad de Medusa y tras cada accion; `--resume` retoma sin repetir ni volver a anunciar nada. Una carta jugada boca abajo cuya respuesta llego tarde se reconoce en el punto de carta y cuenta como jugada; un reparto tardio se acredita leyendo la mano real (no se reparte dos veces).
- **Rejilla del descarte**: `bot_discard_bounds` (centro x, centro z, tamano x, tamano z, rotY de la zona) valida cada hueco con la rotacion de la zona; llena, la rejilla vuelve al primer hueco y apila encima (las cartas se funden en un Deck que `read_discard` lee). Si los limites estan mal y ningun hueco cabe, `start()` lo dice. Si se mueve o redimensiona la zona 906a7a hay que actualizar `bot_discard_bounds`.
- **Salidas de un combate pendiente**: si el atacante o el objetivo deja de estar en juego (Retirar, PV, baja que el bot no vio), el combate se cancela solo (Revelar, Cancelar, Fin de accion, PV, Retirar o Deshacer), la carta vuelve a la mano del bot y la accion no se gasta.
- **Manos iniciales**: si la mano del bot esta vacia al empezar, el bot se reparte 5 de su mazo; si la del humano esta vacia, el bot **no** reparte a su asiento: avisa de que robes tus 5 cartas.
- **Una accion a la vez**: con una accion abierta (Maniobra, Plan o combate ya revelado) los botones de accion se ignoran hasta Fin de accion, asi que un doble clic no gasta las dos acciones.
- **Limpieza**: el panel, las etiquetas y las lineas llevan la marca `sparring` en las notas de GM; al arrancar se borran los restos de una ejecucion que murio sin limpiar y al salir (Ctrl+C) se quita todo, incluido el panel. Solo se tocan objetos cuyo nombre **y** marca son nuestros. Panel por defecto en `[2, 1.8, -24]`, encima de los tapetes.

- **Diales automaticos**: tras cada combate, ajuste de PV, habilidad de Medusa y accion del bot, `set_health_dials` (escritura permitida, no de solo lectura) pone cada dial de `dials` a la vida del motor usando su propio script (`CONFIG.VALUE` con getTable/setTable y `updateVal`), y se relee con `read_health_dials` para comprobarlo; si no coincide avisa y no bloquea. Las Harpias no tienen dial: al caer se retira su miniatura (el bot lo dice). Los botones +1/-1 siguen para el dano de efectos de carta.
- **Anuncios**: el combate dice de donde sale cada total (carta, bono, impulso, defensa) y el bot anuncia lo que descarta. El bot aplica solo los efectos de despues del combate sin decision (Medusa, Horseshoes And Hand Grenades, On Earth As It Is In Hell); el resto sigue siendo del humano.
- Todos los movimientos de cartas (jugar, descartar, sacar de un Deck) son instantaneos: una zona de mano no suelta una carta movida con `setPositionSmooth`.

### Preparacion de la partida (`setup`, por defecto activa en `partida.json`)

- **Sorteo**: `--first random` es el valor por defecto (y la semilla, al azar si no se da `--seed`); `--first human|bot` lo fuerza. Se anuncia "Sorteo: empieza Medusa/Hellboy". El primer jugador ocupa la casilla de salida 1 del mapa y el otro la 2 (reglamento oficial, segun agent-os/memory/projects/unmatched-canarias.md); `start_spaces` en la configuracion solo sirve para forzarlas.
- **Maquina de estados persistida** (`setup.stage` en el guardado, reanudable con `--resume`): `hand` (el bot se reparte 5) -> `mulligan` -> si empieza el bot: `place_bot` (coloca a Medusa y las Harpias solo con su mano y las salidas conocidas, y lo anuncia) -> `wait_human` (el humano coloca a Hellboy y Lobster en la zona de su salida, roba 5 y pulsa **Listo**) -> `begin`. Si empieza el humano: `wait_human_first` (el bot NO coloca; espera) -> Listo -> el bot lee donde estan Hellboy y Lobster y coloca sus Harpias teniendo en cuenta esas casillas -> `begin`. Mientras dura, los demas botones de accion se rechazan. Listo comprueba que Hellboy y Lobster esten en la zona de su salida y que hayas robado.
- **Mulligan** (`mulligan_bot: true|false` y `mulligan_human: true|false`, ambas `true` por defecto). **La regla es de la casa o no esta confirmada**: no hay otra en unmatched-memory ni en la memoria de agent-os (solo la habilidad de Black Widow), asi que Ivan debe confirmar la real y, si no existe, desactivarla con estas claves. Una sola vez, las 5 cartas vuelven al mazo (`return_hand_to_deck`), se baraja (`shuffle_deck`, se comprueba que tenga las 30) y se reparten 5. El bot lo decide con `MedusaAI.should_mulligan` (ninguna carta con la que atacar, o tres o mas que no sirven para atacar) y se anuncia "Medusa hace mulligan" o "Medusa se queda la mano" sin decir las cartas. Es **reanudable**: la decision y cada sub-paso (`mull_step`: start, returned, shuffled, dealt) se guardan, un corte o un fallo se reintenta con Listo sin repetir lo hecho, y la preparacion no avanza mientras la mano de la mesa no coincida con la del motor. El humano usa el boton **Mulligan** del panel durante la preparacion y antes de Listo (una vez): el bot le dice que devuelva su mano, baraje y robe 5, y Listo exige 5 cartas despues.
- **Diales a mano**: antes de escribir un dial se lee; si marca algo que ni es lo ultimo que escribio el motor ni lo que toca ahora, el humano lo ha cambiado a mano y el bot **no lo pisa** (opcion segura: ni pierde su correccion ni un dial cambia el estado del motor): avisa, deja la deuda `dial_debt` y espera a que lo reconcilie con +1 / -1 o lo devuelva. Todo fallo de escritura de un dial deja esa deuda. El dial de destinos solo se da por escrito tras una escritura verificada.
- **Bajas**: toda baja, de cualquier origen (combate, habilidad, A Momentary Glance, Retirar, -1 a 0), dice "<nombre> cae" y que pasa con la miniatura. Las del bot las aparta `_bury` a `dead_spot` y relee la mesa para comprobarlo; las del humano se le piden retirar.
- **Harpias** (`MedusaAI.choose_setup`): en la zona de la salida de Medusa; con Clutching Claws o The Hounds of Mighty Zeus se adelantan (mejor `harpy_score` frente a las piezas rivales), sin ellas se quedan atras. Las mueve con `move_piece` y las verifica.

## Velocidad: un mensaje por boton (F06; solo verificado contra FakeTTS)

Cada mensaje a TTS cuesta ~0.5 s fijos y encadenarlos no ayuda (medido en vivo el 27/10), asi que lo unico que se puede bajar es el numero de mensajes por boton. `python -m sparring.play --timing` escribe, por boton y por accion del bot, cuantos mensajes se enviaron y cuanto tardaron (y una linea por llamada).

- **El clic trae la instantanea.** El script del panel (`ui.handler_script` + `lua.snapshot_lua`) pone "Procesando...", apaga los botones y manda en el mismo `sendExternalMessage` la mesa: mano del bot (CardID), conteo de la mano del humano (solo se cuenta), descartes de las dos zonas (el mazo de robo se excluye por GUID; una carta boca arriba junto al mazo nunca se excluye), cartas boca abajo de los dos puntos de combate, casilla y distancia de cada pieza por GUID y diales. La sesion lee de ahi (`Session._view`) sin preguntar. Solo el primer clic de cada tanda trae una mesa todavia valida; el resto, y `start`/`--resume`, piden una instantanea (`lua.snapshot`, un mensaje).
- **Un script de escritura por paso.** Las escrituras se encolan (`Session._w`) y salen juntas en `lua.composite`: solo compone scripts que ya generaron constructores validados, cada uno en `pcall`, espera dentro de TTS (maximo 2.5 s) a que las piezas esten quietas y la mano del bot tenga las cartas esperadas, y devuelve el estado resultante, que pasa a ser la nueva instantanea. Una lectura solo fuerza la salida de la cola si la cola toca lo que lee. El cierre de cada boton lleva en el mismo mensaje la linea de estado, los botones del panel (`lua.set_panel`) y los anuncios en pantalla.
- **Solo se espera si una lectura discrepa**: `_settle` descarta la instantanea y relee (un mensaje trae todo). La confirmacion con dos lecturas del descarte del humano no hace falta cuando la instantanea es la del clic.
- `SessionConfig.batch` / `live_ui` (por defecto `false` en el codigo, `SessionConfig`, y `true` si `partida.json` no los menciona: `play` los lee con `true` por defecto) activan todo esto; sin ellos la sesion se comporta como antes (un mensaje por lectura y por escritura). `SPARRING_BATCH=1 pytest` pasa toda la bateria por el modo rapido.
- Mensajes por boton en la mesa falsa (con 3 diales y dial de destinos), antes -> ahora: inicio con preparacion 9 -> 4; Maniobra 7 -> 1; Fin de accion 5 -> 1; atacar 12 -> 3; Revelar 17 -> 2; Fin de accion + turno del bot de 2 acciones 43 -> 3 (1 por accion). Antes ademas habia un mensaje de anuncio por cada trozo de 64 caracteres.
- Cambio de comportamiento en modo rapido: Revelar gira las cartas despues de que el motor acepte el combate (en vez de antes), y Plan no espera a ver la carta al pulsar (la reconoce Fin de accion).

## Panel nuevo y reinicio

- Secciones **TURNO** (linea de estado + acciones), **VIDA** (PV por luchador) y **PARTIDA**. La linea de estado ("Tu turno - 2 acciones - esperando Revelar") y los botones apagados (`interactable=false`: Revelar sin combate, objetivos fuera de alcance, botones de preparacion durante la partida...) los actualiza el bot con `lua.set_panel` sobre su objeto propio; nunca el Global. Mismo giro (0 0 270), texto blanco y `panel_scale` configurable.
- **Mulligan** y **Listo** solo se ven en la preparacion; durante la partida los sustituye **Reiniciar partida**, que pide una segunda pulsacion en 3 s (cualquier otro boton la desarma). Reiniciar: `lua.reset_deck` devuelve las cartas de los dos bandos (manos, descartes, boca abajo) a sus mazos y los baraja, los diales vuelven a vida completa y el de destinos a 0, las 6 miniaturas salen del tablero (`dead_spot` del bot; `human_dead_spot` del humano, por defecto la del bot reflejada en x), se borra `estado\sesion.json` y todo vuelve al reparto, el mulligan y la colocacion. Se comprueba en la mesa antes de tocar el motor; si falla se puede repetir.
- El bot coloca tambien al heroe del humano (Hellboy) en su casilla de salida en la preparacion (en cualquiera de los dos ordenes); el humano solo coloca a Lobster Johnson y pulsa Listo.
- Las miniaturas caidas del humano tambien las aparta el bot ("Lobster Johnson cae: lo he apartado."). Un luchador muerto no puede atacar y el mensaje lo dice.
- Descarte del humano: un contador (destinos) solo baja si la carta falta en dos botones distintos; si una carta desaparece del descarte y el mazo de robo crece, el bot avisa de que se ha fusionado con el mazo. Un dial tocado a mano solo bloquea ese dial: los demas se escriben y verifican.
- Etiquetas del suelo (`label_font` configurable, 30 por defecto): giradas 90 grados sobre Y para leerse desde White, justo fuera del borde de su caja que mira a White ("MEDUSA", "HELLBOY", "DESCARTE MEDUSA", "DESCARTE HELLBOY"); `lua.label_position` es el espejo en Python de la formula y los tests comprueban que no se solapan.

## Formas de Hellboy (fuente)

Las reglas de forma salen de la carta de personaje, transcrita en `../unmatched-hellboy-cartas/2026-10-23_2239/unmatched-hellboy-4-personajes.html` (seccion "AHH CRAP!"):
OCCULT DETECTIVE con 5 o menos destinos en el descarte (al empezar el turno, en una casilla de salida rival, puede robar 2); ANUNG UN RAMA con 6 o mas (al empezar el turno descarta 1 carta obligatoriamente y puede mover a Hellboy hasta el BOOST de esa carta; sus ataques suman +2). La forma no es permanente: si bajan a 5 destinos (p. ej. Pancakes!) vuelve a DETECTIVE, por eso se recalcula siempre desde el descarte (`Game.form`).

## Bridge: allowlist

`TTSClient` solo envia Lua generado por los constructores de `tts/lua.py` (cada uno registra el hash de su script); cualquier otra cadena se rechaza. Solo salen los messageID 2 y 3.

## Decisiones de reglas (donde las reglas son ambiguas)

- Todos los turnos tienen 2 acciones (no hay regla de primer turno reducido) y no se puede pasar: una maniobra sin mover roba igual.
- Boost de maniobra: la carta suma su boost al movimiento de cada luchador de esa maniobra.
- Si ambos cancelan efectos en la misma ventana, el defensor resuelve primero y lo cancelado ya no cancela.
- Planned Recklessness: protege del dano de efectos a los luchadores de su dueno durante todo el turno actual; cancela efectos rivales solo si Hellboy esta en OCCULT DETECTIVE.
- La habilidad de Medusa y "su zona": cualquier luchador que comparta alguna zona con ella.
- Las Harpias empiezan en las casillas libres mas cercanas a la salida de Medusa (y Lobster a la de Hellboy).

## Revision 9 y partida 5

- **Identidad de los mazos**: el CardID no identifica un mazo (en el guardado real 12 juegos comparten el DeckID 176). Al empezar, `lua.deck_identities` lee del objeto del mazo el FaceURL/BackURL de su CustomDeck (`Session.load_identities`, un mensaje) y `deal_cards`, `discard_cards`, `reset_deck`, `shuffle_deck` y `return_hand_to_deck` solo tocan cartas con CardID en rango Y esas imagenes; de un Deck se exige que lo sean TODAS sus cartas (salvo `discard_cards`, que saca solo la carta propia). `discard_cards` y `reset_deck` buscan solo en un `lua.Scope` (las dos manos, las dos zonas de descarte y el entorno de los puntos de combate y del mazo), nunca en la mesa entera.
- **Instantaneas selladas**: cada compuesto lleva un numero de secuencia que anota en el panel (`wseq`) y devuelve en su estado; el clic lo copia en su instantanea. La sesion descarta cualquier instantanea anterior a su ultima escritura (`_take_snapshot`, `_view`), y el cliente le quita la instantanea a un evento que llega mientras esta dentro de `call_lua`. El temporizador de 20 s del panel lleva un token por clic: solo el del ultimo puede desbloquear.
- **Procesando...** se libera en `finish()` del compuesto, tras esperar a las piezas (`isSmoothMoving` y `resting`, cada uno bajo pcall). Un compuesto tiene tope de tamano (`MAX_COMPOSITE_BYTES`; `_flush` lo parte) y la linea de estado se vuelve a calcular tras los cierres.
- **Panel**: `panel_position` [-12.5, 1.8, -24.5] y `panel_scale` 4.5 (a la derecha del descarte del humano); `play.floor_layout_warnings` avisa al arrancar si una etiqueta o caja del suelo quedaria bajo el panel (tamano estimado en `lua.panel_footprint`); el objeto que lo lleva se tine casi negro; las etiquetas del suelo flotan a `LABEL_Y` (por encima de las pilas). "Deshacer fin de partida" solo se ve con la partida terminada y no hay avisos de "fuera del tablero" durante la preparacion. Con `--resume` los diales se escriben y verifican en el mismo cierre.
- **BOOST del humano** (Second Shot): Revelar gira las dos cartas y, si la del humano permite potenciar su ataque, el combate queda en `awaiting_boost` (`Pending.boost_wait`, persistido y reanudable). El humano pone una carta de su mano en su descarte y pulsa **Continuar**: el bot lee la carta nueva (no estaba en el descarte al revelar), suma su boost tras el DURING del defensor, resuelve y anuncia "X ataca con Second Shot (2) y potencia con <carta> (+N): total T". **Sin boost** resuelve sin potenciar. Con las cartas giradas Cancelar, Revelar y Fin de accion se rechazan. El valor extra (`Enviar valor`) solo se registra con un combate pendiente.
