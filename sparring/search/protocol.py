"""Lo minimo que la busqueda necesita de un motor de juego.

El buscador (`ismcts.py`) no sabe nada de Unmatched: solo habla con un `SearchState`. El adaptador del motor
actual vive en `adapter.py`; el motor multiheroe (F07) implementa este mismo Protocol y la busqueda le sirve
sin cambios.

Jugadas (`Move`): cualquier valor hashable que el adaptador quiera (tuplas). Dos reglas:
  * `observe(move, viewer)` devuelve `move` tal cual cuando `viewer` es quien la hace; para los demas puede
    enmascarar lo oculto (p. ej. la carta de un ataque boca abajo). La busqueda indexa el arbol de cada jugador
    por lo que ese jugador ve, de modo que el rival simulado no "lee" una carta que en la mesa no veria.
  * `determinize(observer, rng)` sustituye TODA la informacion que `observer` no conoce (manos ajenas, orden de
    los mazos, cartas boca abajo) por una muestra compatible con lo publico. Nunca debe leer la mano real del
    rival: la muestra sale del mazo completo menos lo visto, y de las cartas "conocidas en mano" que el motor
    tenga por un efecto legitimo de mirar la mano.
"""
from __future__ import annotations

import random
from typing import Hashable, Protocol

Move = Hashable


class SearchState(Protocol):
    def clone(self) -> "SearchState":
        """Copia independiente: aplicar jugadas en ella no toca el original."""
        ...

    def player_to_move(self) -> int: ...

    def turn_owner(self) -> int:
        """De quien es el turno (quien mueve puede ser otro a mitad del turno, p. ej. el que defiende). El rollout
        termina al cambiar: la hoja se evalua como el final de turno de quien movia, frente al turno del rival."""
        ...

    def legal_moves(self) -> list[Move]:
        """Jugadas de quien mueve, en la informacion actual (tras determinizar, con la mano muestreada)."""
        ...

    def apply(self, move: Move) -> None:
        """Aplica la jugada y avanza los pasos automaticos (fin de turno, robos obligatorios...) hasta la siguiente
        decision o el final."""
        ...

    def is_terminal(self) -> bool: ...

    def winner(self) -> int | None: ...

    def evaluate(self, player: int) -> float:
        """Valor de la posicion para `player` en [0, 1] (1 = ganada). En terminal, 1 o 0."""
        ...

    def observe(self, move: Move, viewer: int) -> Hashable: ...

    def rollout_move(self, rng: random.Random) -> Move:
        """Jugada barata para la fase de rollout; puede ser un subconjunto sesgado de las legales."""
        ...

    def determinize(self, observer: int, rng: random.Random) -> None: ...
