from ._helper import QueuedHelper
from ._decorator import QueuedDecorator

__all__ = ['QueuedHelper', 'QueuedDecorator', 'queued']

# For now, there is no need to provide a decorator using bounded queues since all items are consumed immediately.
queued = QueuedDecorator()
