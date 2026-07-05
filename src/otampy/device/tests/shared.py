class FakeUART:
    def write(self, data):
        return len(data)

    def read(self, n=None):
        return b""

    def any(self):
        return 0


class FakeLogger:
    def __init__(self):
        self.messages = []

    def debug(self, msg):
        self.messages.append(("debug", msg))

    def info(self, msg):
        self.messages.append(("info", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))

    def critical(self, msg):
        self.messages.append(("critical", msg))
