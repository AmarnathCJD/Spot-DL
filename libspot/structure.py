class Closeable:
    def close(self) -> None:
        raise NotImplementedError


class MessageListener:
    def on_message(self, uri: str, headers, payload: bytes):
        raise NotImplementedError


class PacketsReceiver:
    def dispatch(self, packet):
        raise NotImplementedError


class RequestListener:
    def on_request(self, mid: str, pid: int, sender: str, command):
        raise NotImplementedError


class Runnable:
    def run(self):
        raise NotImplementedError


class SessionListener:
    def session_closing(self, session) -> None:
        raise NotImplementedError

    def session_changed(self, session) -> None:
        raise NotImplementedError


class SubListener:
    def event(self, resp) -> None:
        raise NotImplementedError
