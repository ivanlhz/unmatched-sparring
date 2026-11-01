# Plan: bot adaptable a cualquier héroe (27/10/2026)

Diseño de Opus (solo lectura). Pendiente de aprobar por Iván; no se toca hasta que F05 (Medusa vs Hellboy jugable) esté estable.

## Idea
Motor, esqueleto de combate, sesión, guardado y puente TTS se quedan. Lo propio de cada héroe pasa a:
- `data/heroes/<slug>.json` (HeroDef: vida, movimiento, cuerpo a cuerpo/distancia, compañeros con cantidad, formas, contadores, disparadores, pasivas), importado de unmatched-memory + overlay a mano.
- `data/heroes/<slug>.cards.json` con efectos estructurados por momento (immediately/during/after/scheme/ongoing).
- Intérprete de primitivas reutilizables en `sparring/effects/` (daño, curar, robar, descartar, mover, colocar, revivir, cancelar, modificar valor, estados, contadores, esquemas permanentes, ver mano rival, elegir N, opcional). Regla: una primitiva solo entra si la usan 2+ cartas; lo demás, plugin Python por héroe.
- Elecciones del humano por el panel (botones de opción/objetivo) con PendingEffect persistido y reproducible al reanudar; movimientos siguen siendo físicos.
- IA genérica (`sparring/ai/`): modelo de mano rival, generador de acciones, evaluación por simulación de efectos sobre un clon, ajustes por héroe en `data/ai/<slug>.json`. MedusaAI queda de referencia hasta que la genérica la iguale en el simulador (±3 puntos en 500 partidas).
- Config TTS por héroe en `data/tts/<slug>.json`; `config/partida.json` gana `bot_hero`/`human_hero` (por defecto medusa/hellboy).
- Cartas no codificadas: el bot anuncia el texto y las juega solo por valor/boost; nada se rompe al crecer el roster.

## Viabilidad caja Hellboy (Hellboy, Abe Sapien, Baba Yaga, Liz Sherman)
- Cartas: 49/55 (89 %) con primitivas, 52/55 (95 %) con el protocolo de información oculta.
- Habilidades: Hellboy y Baba Yaga con datos; Abe y Liz con plugin.
- 5 plugins: abe:perfect_shot, baba:remove_painful_memory, liz:incinerate, abe:uncanny_intuition, liz:wildfire.
- Medusa: 100 % con primitivas.

## Pasos (cada uno con la suite en verde y Medusa vs Hellboy funcionando)
0. Fijar el comportamiento actual con tests dorados (simulador, transcripción de sesión FakeTTS, ida y vuelta del guardado).
1. HeroDef + cargador sin cambiar el comportamiento.
2. Construir la partida desde HeroDef.
3. Formas y contadores desde datos.
4. Intérprete de efectos (aún sin conectar).
5. Medusa en el DSL (test diferencial contra el código actual).
6. Hellboy en el DSL + combate genérico.
7. Elecciones por el panel + reanudar a mitad de efecto.
8. Disparadores genéricos.
9. Contadores y diales genéricos.
10. Config genérica.
11. IA genérica tras un flag, con la puerta del simulador.
12. Rival con guion genérico + matriz de simulación.
13. Resto de la caja Hellboy (datos, 5 plugins, esquemas permanentes, ver mano, ataque boca arriba) + partida en vivo supervisada por héroe.
14. Roster completo con informe de cobertura de efectos.

## Riesgos
Reanudar a mitad de efecto; refactor de session.py (1588 líneas); IA genérica más floja; huecos en los datos de unmatched-memory (restricciones de luchador, etiquetas de destino/ardiente, textos de los Pactos); mapear hojas de CardID a mano.

## Preguntas para Iván
1. Agentes de Abe: cuántos empiezan en el tablero y cuántos en reserva.
2. Cartas ardientes de Liz (las 15).
3. Restricciones de luchador de Abe, Baba Yaga y Liz: ¿de la hoja de TTS como con Hellboy?
4. Texto permanente de cada Pacto de Baba Yaga.
5. ¿Puede el bot leer tu mano solo cuando una carta dice "mira la mano del rival"?
6. Elecciones con botones y movimientos físicos: ¿bien?
7. ¿Los otros héroes vienen del mismo mod de TTS?
8. Cambio de forma cuando el bot lleva a Hellboy: ¿cambia él la miniatura o te lo pide?
9. ¿Basta el nivel de MedusaAI como base para todos o ajuste por héroe desde el principio?
10. Mapas: ¿solo B.P.R.D. HQ o también Azuchi y el resto?
