class StopPipeline(Exception):
    def __init__(self, exception: Exception = None, *args):
        super().__init__(*args)
        self.exception = exception
