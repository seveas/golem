class memoize:
    def __init__(self, function):
        self.function = function
        self.memoized = {}

    def __call__(self, *args):
        args_ = args
        if args and hasattr(args[0], 'path'):
            args_ = (args[0].path,) + args[1:]
        try:
            return self.memoized[args_]
        except KeyError:
            self.memoized[args_] = self.function(*args)
        return self.memoized[args_]
