# Abe Sapien (caja Hellboy)

Datos verificados el 28/10/2026 contra el save del torneo (`saves\Unmatched Official Tournament Table October 2026 (Hellboy).json`): hoja de cartas 194 (8x4, FaceURL de la bolsa "Abe Sapien", GUID a959bb), carta de heroe 19500 y fichas. Solo datos y especificacion; el motor no ejecuta nada de esto todavia.

## Resumen

- Vida 13, movimiento 2, a distancia. Habilidad UNCANNY INTUITION: dos fichas de intuicion; cuando Abe hace dano de combate a un luchador adyacente activa una; cuando atacan a Abe con una activa, la desactiva, roba 1 y el ataque se juega boca arriba.
- Ayudantes: B.P.R.D. Agents, vida 1, movimiento 2, a distancia, x3. En TTS son tres fichas llamadas Victor, Carla y Kate. En el motor: un ayudante `agent` con count 3 (agent1..agent3).
- Mazo (30): 11 cartas solo de Abe (Faster. Stronger. x2, Advanced Psychometry x3, Perfect Shot x2, Every Possible Angle x2, Counterhex Shield x2, B.P.R.D. Utility Belt x2), 3 solo de agentes (Secure The Scene) y 16 ANY.
- CardID = 19400 + idx (hoja 194). Carta de personaje: 19500.

## Ficheros

- `data/heroes/overlay/abe-sapien.json`: hoja de CardID, restricciones, ayudantes con `start_on_board`/`reserve`/`tts_tokens`, dos disparadores de la habilidad como datos.
- `data/heroes/abe-sapien.json`: HeroDef regenerado con `tools/import_hero.py abe-sapien` (`--check --all` pasa).
- `data/heroes/effects/abe-sapien.json`: habilidad y 14 cartas en ops del vocabulario comun, primitivas nuevas, plugins, informacion oculta y preguntas.
- `tests/test_hero_abe_sapien_data.py`: hoja, copias, HeroDef, cobertura de efectos y vocabulario.

## Decisiones

1. **Agentes: 3 en el tablero, 0 en reserva.** La carta de heroe marca "START HEALTH" con tres puntos y "x3", la misma notacion que las Harpias de Medusa (que empiezan todas en mesa); el save trae tres fichas y nada que haga de reserva. "Summon a B.P.R.D. Agent in Abe's zone" (Secure The Scene): `revive` de un agente abatido con su 1 de vida; sin agentes caidos, el dueno coge uno vivo y lo coloca (`place`) en la zona de Abe (decision de Ivan, 28/10).
2. **Uncanny Intuition NO necesita plugin.** Son dos disparadores con tres primitivas: `counter` de fichas (0..2), `draw` y `reveal` del ataque antes de la defensa. El "ataque boca arriba" lo comparte Perfect Shot, asi que es primitiva y no codigo de un heroe. El plan preveia `abe:uncanny_intuition`; queda como respaldo solo si el motor no quiere contadores de fichas ni el momento `attacked`.
3. **Perfect Shot si es plugin** (`abe:perfect_shot`): decidir al jugar si va boca arriba, anunciar una prediccion y compararla en DURING COMBAT no cabe en el DSL (no hay momento "al jugar" ni "guardar y comparar") y es la unica carta de la caja que lo necesita.
4. Convenciones de ops: `target` con eleccion la hace `who_chooses` (owner por defecto); `same` repite el ultimo objetivo elegido; `push` mueve a un rival y lo dirige el dueno del efecto; `modify_value` con `set` fija el valor (Shock And Awe "becomes 4").

## Cobertura

- 14 cartas: 13 con primitivas, 1 con plugin (Perfect Shot). Habilidad con primitivas.
- Primitivas nuevas o extendidas pedidas: `recover_from_discard` (Ward And Prepare), `counter` de fichas, `reveal` de la carta de ataque, `modify_value` con `set`, `status` con nombres y caducidad (cannot_gain_actions, cannot_draw, next_attack_bonus, immune_to_enemy_effects), momentos de disparo `combat_damage_dealt` y `attacked`.
- Informacion oculta: Advanced Psychometry y Every Possible Angle (mirar la mano), Perfect Shot y la habilidad (ataque boca arriba), Shock And Awe (descarte a eleccion del rival) y Ward And Prepare (descarte publico). Regla: el bot lee la mano solo cuando la carta lo dice, la recuerda en KnownHand y la descuenta segun salen cartas. Every Possible Angle ademas deja conocida la siguiente carta que robara el rival (KnownHand necesita un `top_of_deck`).

## Discrepancias con unmatched-memory

- **Counterhex Shield**: la carta real anade "Ongoing: Other players' effects can't damage your fighters, move your fighters, or force you to discard cards. Discard this at the start of your next turn." unmatched-memory solo tiene "Draw 1 card. Gain 1 action." Manda la carta: las dos entradas de la hoja del overlay llevan `text` con el texto real y el importador lo prefiere al de unmatched-memory (`"text": entry.get("text") or card_text(src)`, misma convencion que Liz). Queda corregir la fuente si Ivan quiere que coincidan.
- **Agentes**: unmatched-memory trae tres entradas (Carla, Kate, Victor) con cifras iguales; la carta de heroe los llama "B.P.R.D. AGENTS" y la restriccion de carta "B.P.R.D. AGENT". Un solo ayudante con count 3; los nombres de las fichas quedan en `tts_tokens`.
- Valores, impulsos, tipos y copias de las 14 cartas coinciden con la fuente.

## Decisiones de Ivan (28/10)

- agentes: 3 en tablero; summon = revivir un abatido con 1 de vida en la zona de Abe o, sin abatidos, coger uno vivo y colocarlo en un espacio de la zona de Abe (Secure The Scene).
- Uncanny Intuition: tambien activa ficha cuando Abe defiende y hace dano de combate a un atacante adyacente.
- Perfect Shot: se puede predecir cualquier valor de 0 a 7; si el rival no defiende con carta, no acierta.
- Every Possible Angle contra el bot: el bot pone su mano boca arriba (fila de look_spot, como F16) y hace ping sobre las cartas.
- Counterhex Shield: el texto real (con ONGOING) se corrige tambien en unmatched-memory.
- el valor de una carta nunca baja de 0 en CADA paso, y los efectos se resuelven en orden de momento (IMMEDIATELY antes de DURING; mismo momento, primero el defensor): Flame Lash (1) contra Arcane Dampener (IMMEDIATELY -3) queda en 0, y luego el impulso de Flame Lash en DURING (+3) la deja en 3.

## Preguntas abiertas

- 6. Fichas de agentes en TTS: se llaman Victor, Carla y Kate; el motor los numera agent1..agent3. Hace falta el mapeo fid -> GUID en la config de la partida (paso 10 del plan), igual que las Harpias.
- Every Possible Angle: como registra el motor la carta del bot que vuelve encima de su mazo (pasa a conocida por el humano: no afecta a la informacion del bot).
