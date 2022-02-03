from typing import Union


class EntityNotFoundError(ValueError):
    def __init__(self, peer: Union[int, str]):
        self.peer = peer
        super().__init__(f"Entity not found: {peer}")
