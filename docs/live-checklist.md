# Checklist de la primera prueba en vivo (TTS)

> Nota: este documento esta en espanol a proposito (es para Ivan, en la mesa; el README y los docs de uso ya estan en espanol; la regla "todo en ingles" es para el codigo). Marca `- [ ]` segun avanzas. Los puntos marcados **(E2)** dependen de la fase E2 (zona ONGOING, puerta de habilidad, botones de esquema), que no esta en master al escribir esto: si no esta mergeada, saltalos.
> Marcado *(OK 29/10)*: comprobado en la primera partida real (bot Hellboy vs Liz humana). El resto esta verificado solo contra FakeTTS. Esto es lo que NUNCA se ha visto en una mesa real.

## 1. Antes de empezar

- [x] **Backup del guardado**: en TTS, Guardar como "pre-sparring" (y copia el `.json` de `saves\`). Si algo se rompe, recargas ese. *(OK 29/10)*
- [x] Mesa abierta con la partida cargada (B.P.R.D. HQ, Green = bot, White = tu). Terminal en la carpeta del proyecto. *(OK 29/10)*
- [x] Comandos (PowerShell): *(OK 29/10)*
  - Solo leer / calibrar / detectar heroes (no cambia nada): `uv run python -m sparring.play --config config\partida.json --read-only`
  - Jugar: `uv run python -m sparring.play --config config\partida.json --first human` (`--first bot|random`, `--seed N`)
  - Reanudar tras cierre o recarga de TTS: `uv run python -m sparring.play --config config\partida.json --resume`
  - Sacar de la bolsa interior lo que falte en la mesa (nunca con `--resume`): `--unpack`
  - Forzar heroes: `--bot-hero <slug> --human-hero <slug>` (medusa, hellboy, abe-sapien, baba-yaga, liz-sherman; no el mismo en los dos lados)
  - Medir mensajes y tiempos por boton: `--timing`. IA por busqueda: `--ai ismcts`. Pausa del bot: `--bot-pause N`.
- [x] Ctrl+C sale limpio (los rectangulos y etiquetas del suelo se borran al salir). *(OK 29/10)*

### Calibracion de posiciones (`config\partida.json`)
Con `--read-only` mira el informe y ajusta lo que este mal. Prueba con una carta en cada sitio.
- [ ] `bot_card_spot` / `human_card_spot` (zona de combate, boca abajo) y `off_board_dist` (4.0 es estimacion; compara con las distancias del informe).
- [ ] `bot_discard_spot` / `bot_discard_bounds` / `bot_discard_step` / `bot_discard_rows`: el descarte del bot queda en rejilla ordenada dentro de la zona 906a7a.
- [ ] `dead_spot` / `human_dead_spot` (donde se apartan miniaturas caidas, 1.5 en x entre piezas; son estimaciones).
- [ ] `look_spot` / `look_step` (fila del boton **Mirar mano**: delante de tu asiento, sin pisar panel, manos, descartes ni cajas de combate; el arranque avisa si pisa algo).
- [ ] `bot_row_spot` / `bot_row_step` (fila que abren tus cartas que miran la mano del bot: Confront, Advanced Psychometry, Remove A Painful Memory, Every Possible Angle; junto a sus zonas de combate y ONGOING).
- [ ] `token_spot` (donde el bot deja las fichas de Intuicion de Abe; sin clave, junto a su mazo).
- [x] **(E2)** `human_ongoing_spot` / `bot_ongoing_spot`: zona ONGOING debajo de la zona de combate, de ambos bandos. *(OK 29/10)*
- [ ] `panel_position` / `panel_scale`: el panel se ve y se pulsa bien desde tu asiento; los rectangulos DESCARTE/COMBATE del suelo no quedan bajo el panel.
- [ ] `bot_unpack_spot` / `human_unpack_spot` solo si usas `--unpack`.

### Deteccion de heroes (`--read-only`)
- [x] Con `bot_hero`/`human_hero` en `"auto"`: el informe da el heroe correcto de cada bando (un Deck o Card SUELTO con CardID de su rango, el mas cercano al `*_deck_spot`). Si es dudoso, se niega a empezar y lo dice. *(OK 29/10)*
- [x] Repite con cada pareja de heroes que vayas a probar (cambiando lo que hay en mesa). *(OK 30/10)*
- [x] El informe no da "no encontrado" para miniaturas, dials, mazo, descarte ni fichas (1644a3 Hellboy, 5a17e9 Abe). *(OK 30/10)*
- [x] Informe de objetos puente (tipo/rotacion/estados): anota el **tipo** de 5a17e9 (bolsa / bolsa infinita / pila / ficha suelta) y de 1644a3, y la rotZ actual de 1644a3. *(OK 30/10)*

## 2. Arranque

- [x] Sin `--read-only`: dibuja los rectangulos DESCARTE y COMBATE de ambos y crea el panel (`SparringPanel`). Sin errores en la terminal. *(OK 29/10)*
- [x] Preparacion (`setup`): el bot reparte 5, mulligan (una vez); si empieza el bot, coloca sus piezas; tu colocas las tuyas y pulsas **Listo**. **Mulligan** / **Listo** aparecen solo cuando toca. *(OK 30/10)*
- [x] El panel responde al primer clic ("Procesando..." y se reactiva). *(OK 29/10)*
- [x] (`--timing`) anota mensajes y tiempo de un boton normal (esperado ~1 mensaje, ~0.5 s por mensaje). *(OK 30/10)*
- [ ] Pausa de anuncio del bot (`action_announce_hold`, 2 s): cada accion del bot se anuncia en el chat, espera y luego se escribe en la mesa; las tuyas no esperan. Desde 682c769 tambien cuando atacas tu y el bot responde moviendo cartas o piezas (Incinerate). *(31/10: parece mejor, sigue en prueba)*

## 3. Por heroe

Cada heroe tiene dos bloques: **H** (lo juegas tu) y **B** (lo juega el bot). Lo que vale para los dos lados va en **H y B**.

### Plantilla comun (repitela para cada heroe y cada lado)
- [ ] Estado inicial correcto (piezas en salida, dials al maximo, mazo de 30, mano de 5).
- [ ] Una carta **IMMEDIATELY**: se aplica una vez; el chat la narra.
- [ ] Una carta **DURING**: afecta al dano/valor correcto.
- [ ] Una carta **AFTER**: se aplica tras resolver; el combate no se queda colgado.
- [ ] Un **esquema**: efecto + carta al descarte.
- [ ] Un **ONGOING** y luego otro que lo **reemplaza** (solo uno por jugador; el primero va al descarte). **(E2)** la carta queda fisicamente en la zona ONGOING de su lado y la sustituta ocupa su sitio.
- [ ] La **habilidad** del heroe.
- [ ] B: el chat dice lo que hizo cada carta y nombra lo que te toca descartar.
- [x] H **(E2)**: puerta de habilidad de inicio de turno en el panel: bloquea las acciones hasta **Fin de accion**. *(OK 30/10)*
- [ ] H **(E2)**: movimientos opcionales ofrecen **Ninguna**.

### Medusa
**B (bot)**
- [x] Mueve Harpias; Winged Frenzy devuelve una Harpia caida **siempre** (obligatorio, primera casilla libre de su zona). *(OK, confirmado por Ivan 31/10)*
- [x] Piezas caidas (Harpias) van al `dead_spot`. *(OK, confirmado por Ivan 31/10)*

**H (tu)**
- [ ] Out Of Time ("BOOST this card" = boost desde la mano, como siempre).

### Hellboy
**H y B**
- [x] Setup: ficha **1644a3** en **OCCULT DETECTIVE** (azul, rotZ 180). *El giro es incondicional: debe empezar asi.* *(OK 29/10)*
- [x] Crown Of Flame (**(E2)** espera tu descarte), Planned Recklessness, Second Shot, Horseshoes, Right Hand Of Doom, B.P.R.D. Training, On Earth. *(OK 30/10)*
- [ ] Glimpse Of Hell, Confront (ver Informacion oculta).

**B (bot)**
- [x] Cambio a **ANUNG UN RAMA**: `set_state` entre las miniaturas f9789a <-> e6f06e, la ficha 1644a3 gira (rotZ 180 = OCCULT DETECTIVE, rotZ 0 = ANUNG UN RAMA) y **ping** sobre ficha y miniatura; sin miniaturas duplicadas. *(OK 29/10)*
- [x] Vuelta a OCCULT DETECTIVE (menos de 6 destinos) gira de vuelta y hace ping. *(OK 31/10)*
- [x] El **Destiny Dial** (e17c66) sigue los destinos del descarte del bot (sube y baja). *(OK 31/10, tras el arreglo bf91f02)*
- [ ] Inicio de su turno, anunciado antes de mover en la mesa: descarta y mueve (ANUNG) *(OK 31/10)*; roba 2 si empieza en DETECTIVE **en tu casilla de salida** *(falta verlo)*.
- [x] **Pancakes!**: elige dos efectos que hacen algo y el chat nombra los dos ("recupera 2 (11 -> 13) y roba 2"). *(OK 31/10)*
- [ ] `card_to_deck_bottom` en Pancakes!: las cartas que devuelve van **abajo** de su mazo.
- [ ] IA (31/10, 2c92014 y 24cd9c3): en ANUNG ataca mas (cuenta su +2), casi no hace maniobras sin mover a nadie, usa a Lobster cuando tiene a tiro, y no se gasta el mazo si la partida va a durar mas que el.

**H (tu)**
- [x] **(E2)** puerta de habilidad de inicio de turno (robo / ANUNG) bloquea hasta **Fin de accion**. *(OK 30/10)*
- [x] **(E2)** esquemas con boton **Pancakes!** y **Posthumous Power**; reanudar a mitad de esquema. *(OK 30/10)*
- [ ] Glimpse Of Hell defendiendo contra un AFTER del bot que te hace descartar (Fleeting Moments): primero robas 2 y metes 1 en el mazo, Fin de accion; luego el descarte al azar sobre tu mano de ese momento, Fin de accion; y despues la carta que robas (81132f9, 19bbe67).

### Abe Sapien
**B (bot)**
- [ ] Muestra 0/1/2 fichas de Intuicion **tomando copias de 5a17e9** (`take_token_copy`: takeObject o clone segun el tipo). Esperado: aparecen en `token_spot`, distintas de la original, sin mover la fuente.
- [ ] Al gastar una, `remove_token` quita la ultima copia (desaparece la copia, no la original).

**H (tu)**
- [ ] Pones tu las fichas a mano; el contador se sincroniza.

**H y B**
- [ ] Faster. Stronger., Secure The Scene, Leap Away, Concussion Device, B.P.R.D. Training, Utility Belt, Arcane Dampener, Cold Iron (bloqueo), Ward And Prepare, Counterhex Shield, Shock And Awe.
- [ ] UNCANNY INTUITION y Perfect Shot: ver Informacion oculta.

### Baba Yaga
**H y B**
- [x] Setup: **Koschei ya esta en el tablero** al empezar (si no, revisa `start_on_board` en `data/heroes/baba-yaga.json`). *(OK 30/10)*
- [ ] Pactos: ONGOING, solo uno a la vez; **Pact Of Freedom** (no atacar como primera accion) y **Cold Iron** bloquean en el panel (seccion 4).
- [ ] Iron Teeth, Death's Release, Foul Journey, Hasten Towards Death, Deathless, Exploit, The Time For Deals Is Done, Bound In Blood, Out Of Time.
- [ ] Koschei cae/vuelve: miniatura al `dead_spot`; "Summon" lo pone lo mas cerca de Baba Yaga con vida 3.

**H (tu)**
- [ ] FATEFUL BARGAINS (Koschei en la misma zona, dano de efecto): **(E2)** pregunta con boton.
- [x] **Pact Of Secrecy**: **(E2)** botones **0 / 1 / 2**; limite de mano 3 para todos. *(OK 31/10)* Resumen del chat sin "miras la mano del bot" y separado por jugador (f527ae5): *falta verlo*.
- [ ] Pact Of Time: mueves tu la carta del descarte al mazo y pulsas **Hecho** (bb95930).

**B (bot)**
- [ ] FATEFUL BARGAINS: decide y lo dice.
- [ ] Pact Of Secrecy: el bot te pregunta cual conservas (los titulos pueden salir como marcadores). Pact Of Secrecy / Time del bot sobre ti: solo chat; la mesa se sincroniza por conteo.
- [ ] Read The Bones: lo que toma sale como robo de arriba (el orden real del mazo no se conoce).

### Liz Sherman
**H y B**
- [ ] Pyrotechnics (deja una burning abajo del mazo), Fireball, Burning Barrier, B.P.R.D. Training.

**B (bot)**
- [ ] Cartas **burning** (BOOST 0): no las usa de boost; descartadas por Wildfire vuelven a la mano.
- [ ] **Wildfire** (inicio de su turno): descarta la carta de abajo y se proyecta en mesa; cuesta 1 mensaje extra antes de su primera accion (anota si molesta).
- [ ] **Excepcion**: una burning descartada por limite de mano (7) al fin de turno **NO** vuelve a la mano; se queda en el descarte.
- [ ] **Incinerate** del bot: respondes Si/No en el panel antes del dano.
- [ ] Fleeting Moments / Confront del bot: el chat **nombra la carta** que debes descartar; la descartas tu.
- [ ] Wildfire devuelve una carta que tu Confront le hizo descartar: el chat dice "El bot se queda X (Wildfire la devuelve)".

**H (tu)**
- [x] **(E2)** puerta de habilidad de inicio de turno (Wildfire) y Fight Or Flight. *(OK 29/10)*
- [x] **Fight Or Flight** como ONGOING: el +1 dura hasta el inicio de tu siguiente turno y ahi se va. *(OK 31/10)*
- [x] Tu ONGOING que caduca o sale de juego: el bot hace ping, dice el motivo, espera `ongoing_hold` y la pone **encima de tu descarte** (`card_to_discard`). *(OK 31/10: Fight Or Flight caducada)*
- [x] **Feint**. *(OK 31/10)*
- [x] **Evade**: robas 1. *(OK 31/10)*
- [ ] Evade defendiendo contra un ataque que te hace descartar (Clutching Claws de las Harpias): la carta de Evade te llega **antes** de pedirte el descarte y cuenta para el (1e8709c).
- [ ] **Flame Lash**: DURING real con la carta de **abajo del mazo** como boost **(E2)**.
- [ ] **Incinerate** contra el bot **(E2)**: el chat dice si paga, no paga o no puede; si paga, nombra las 2 cartas, espera la pausa de anuncio y despues las mueve (6c14d9c, 682c769).
- [x] Searing Clarity con botones del panel. *(OK 29/10; desde bb95930 ya no hay botones, ver la linea siguiente)*
- [ ] Searing Clarity y Rekindle **sin botones**: mueves tu la carta del descarte al mazo y pulsas **Hecho**; el bot la reconoce; luego "Pulsa Fin de accion cuando termines"; prueba tambien con el descarte apilado (bb95930).

### Informacion oculta (cartas que miran la mano del bot, y las del bot sobre ti)
- [ ] **Fila de la mano del bot**: al jugar Confront Any Demon or God (solo si pierdes), Advanced Psychometry (adyacente), Remove A Painful Memory (con un ONGOING) o Every Possible Angle, el bot pone su mano **boca arriba en fila** en `bot_row_spot` y hace **ping** sobre cada carta (`ping_points`). El boton **Mirar mano** usa otra fila, en `look_spot`.
- [ ] **Los pings del propio bot no eligen por ti** (9335eab): con la fila abierta, el bot no "elige" una carta solo. *(31/10 fallo con Remove A Painful Memory: eligio Posthumous Power en 1 s; arreglado, falta verlo. Si vuelve a pasar, ampliar `BOT_PING_WINDOW`.)*
- [ ] La lectura de tu mano ocurre **una sola vez por look** (un mensaje `read_hand`), solo cuando una carta del bot te mira; fuera de eso, no.
- [ ] **Elegir por ping** (Tab sobre la carta, `onPlayerPing`) **o por boton** del panel (los botones nombran la carta). Esperado: Confront -> a su descarte; el resto vuelve a su mano. Plan B: una carta boca abajo + Fin de accion.
- [ ] **Every Possible Angle**: la carta elegida va **encima del mazo** del bot (`putObject` sobre el mazo, mismo giro); prueba tambien con el mazo en 1 carta.
- [ ] **Solo mirar** (Revelar): se cierra con Fin de accion o Cancelar (todo a la mano); un ping se rechaza.
- [ ] **Remove A Painful Memory**: tuyo -> el bot dice "descarta X" / "se queda X" y el resumen no dice "roba -1"; del bot -> botones "Descartar <carta>" / "Coger 2".
- [ ] **Perfect Shot**: B coloca, **gira boca arriba** en el mismo script y anuncia la prediccion. H: al **Revelar** salen **Valor 0..7** (+ "Mas" -> **Boca abajo**, segunda pagina) antes de que el bot defienda; boca arriba es publico y el bot lo sabe.
- [ ] **UNCANNY INTUITION**: B ataca -> carta boca abajo y se **gira** boca arriba en el mismo script, nombrada en el chat. H ataca al Abe del bot -> el chat avisa en Ataque; al Revelar el bot gasta ficha y roba **antes** de elegir defensa (la robada puede ser la defensa); pon el ataque boca abajo (se gira al Revelar).
- [ ] Fallo parcial (una carta no se mueve): la fila sigue, el bot lo dice una vez y eliges por boton; la mesa gana en la siguiente lectura.

## 4. Panel y botones

- [x] Los botones de eleccion de una carta **solo aparecen cuando se juega** (ocultos, **nunca en gris**). *(OK 30/10)*
- [x] Las etiquetas cambian (`UI.setValue` sobre un Button): "Valor 3", "Descartar X", "Coger 2". Si no se actualizan, apuntalo (punto **verify live**). *(OK 29/10)*
- [ ] **Cancelar** durante una pausa de combate: funciona; si todas las opciones se rechazan y no puedes salir, apunta cual (la salida es Reiniciar).
- [ ] Restricciones **bloqueadas** (no solo avisadas): Pact Of Freedom, Cold Iron (si robas fisicamente igual, el bot lo acepta al sincronizar y lo dice).
- [ ] Maniobra con BOOST 0 (burning de Liz): deberia avisar en el chat (item pendiente; si no avisa, apuntalo).
- [ ] **Mirar mano del bot**: **oculto** salvo que una carta lo permita; no gasta accion.
- [ ] 0/1/2, "Ninguna", Si/No, Valor 0..7: ningun boton se queda a medias tras un doble clic.

## 5. Guardar y reanudar

Para cada caso: Ctrl+C (y recarga TTS si quieres), luego `--resume`. Esperado: nada se repite ni se reanuncia; el panel vuelve al mismo punto.
- [ ] A mitad de una **pausa de combate** (esperando Revelar o un boton de efecto).
- [ ] Pausa tras haber movido/hecho boost el bot a mitad de combate (camino proyeccion -> reanudar; **sin test**).
- [x] A mitad de un **esquema** que espera tu respuesta (Pact Of Secrecy, Pancakes!, Posthumous Power) **(E2)**. *(OK 30/10: reanudar a mitad de esquema, linea 71)*
- [ ] A mitad de una **fila de informacion oculta** (`look_spot`): vuelve la fila y se repite el aviso del modo (`pick` / `reveal`).
- [ ] A mitad de Perfect Shot (botones de prediccion) y de FATEFUL BARGAINS **(E2)**.
- [ ] Tras un cambio de turno con Wildfire pendiente.
- [ ] Guardado ajeno/antiguo/de otra mesa: `--resume` lo rechaza con mensaje claro.
- [ ] A mitad de la pausa entre dos AFTER (despues de tu Glimpse, antes de Fleeting) y a mitad de un descarte con robo pendiente: no se repite nada y la carta debida llega una vez.
- [x] Guardado de antes de configurar el Destiny Dial del bot: `--resume` lo acepta. *(OK 31/10)*

## 6. Puente TTS (primitivas nunca vistas en real)

Anota OK / fallo y que paso. Un fallo de proyeccion se dice **una vez** ("hazlo tu"); no hay reintento.
- [ ] `card_to_deck_bottom`: carta del descarte del bot va **abajo** del mazo (Pancakes! del bot).
- [ ] `shuffle_into_deck`: carta(s) del descarte al mazo y baraja.
- [ ] `hand_to_deck`: carta de la mano del bot al mazo (`putObject` directo desde la zona de mano; "abajo" = mazo girado).
- [ ] `return_card_to_hand`: carta del descarte (o del combate, al cancelar) vuelve a la mano del bot.
- [ ] `move_piece`: el bot mueve una **miniatura tuya** por efecto (por GUID); si falla dice "muevela tu".
- [ ] `set_state` + `flip_token` + `ping_objects` (Hellboy) y `take_token_copy` / `remove_token` (Abe): ver seccion 3.
- [ ] `onPlayerPing` llega al script del panel con tu asiento y el objeto esperado (si TTS no da objeto, se usa la carta de la fila a menos de 1.6).
- [ ] `read_hand` de tu asiento: un mensaje por look; el bot nunca lee tu mano fuera de un look.
- [ ] Carta boca arriba justo tras colocarla (`play_card_face_down` + giro en el mismo script): se ve como esperas.
- [ ] Mensajes y latencia (`--timing`): boton normal ~1 mensaje; turno de Liz con Wildfire +1; un look +1. Anota cualquier boton que tarde mas de unos segundos.
- [ ] Avisos de TTS lento: si sale "TTS no devolvio valor (esta ocupado, en pausa o recargando...)", anota la hora y que hacias (568c6bf: ahora espera 8 s mas antes de avisar).

## 7. Que apuntar si algo falla

Por cada fallo:
- [ ] Que hacias (heroe, lado H/B, carta, momento, boton), que esperabas y que paso.
- [ ] Las **lineas del chat** del bot y la salida de la terminal (con traceback si hay).
- [ ] `estado\sesion.json` **justo despues** del fallo (antes de seguir jugando); el guardado de TTS si la mesa quedo rara.
- [ ] Captura de pantalla de la mesa y del panel.
- [ ] El informe de `--read-only` (deteccion/calibracion) o la salida de `--timing` (latencia).
- [ ] Si recargaste: con o sin `--resume`; y recuerda que tienes el guardado "pre-sparring".
