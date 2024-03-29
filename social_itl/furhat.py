import asyncio
import websockets.client as client
import websockets
import json
from enum import Enum
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, List, AsyncIterator, AsyncGenerator
from .utils import get_logger

class SpeechType(Enum):
    FINAL = 0
    INTERIM = 1
    SILENCE = 2
    MAXSPEECH = 3
    INTERRUPTED = 4
    FAILED = 5
    ABORTED = 6

class SpeakerRole(Enum):
    TEACHER = 0
    EMPLOYEE = 1
    CUSTOMER = 2

class UserSpeech():
    def __init__(self, event: Dict):
        self.text = event.get("text")
        self.confidence = event.get("conf")
        self.type = SpeechType(event.get("type"))
        self.length = event.get("length")
        self.time = event.get("time")
        self.userId = event.get("userId")
        self.audioLength = event.get("audiolength")
        self.role = None

    def __str__(self):
        return str(self.__dict__)

class DisconnectError(Exception):
    pass

class Furhat():
    def __init__(self, host, port=80):
        self.host = host
        self.port = port
        self.websocket = None
        self.disconnect_event = asyncio.Event()
        self.subscriptions: Dict[str, List[asyncio.Queue]] = {}
        self.user_locations = {}
        self.logger = get_logger("Furhat", "furhat", True)
        self.custom_loggers = []

    @asynccontextmanager
    async def connect(self):
        self.disconnect_event.clear()
        self.websocket = await client.connect("ws://{}:{}/api".format(self.host, self.port))
        recv_task = asyncio.create_task(self.recv())
        async def heartbeat():
            while True:
                await asyncio.sleep(1)
                await self.send({ "event_name": "ServerEvent", "type": "Heartbeat" })
        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            yield self
        finally:
            recv_task.cancel()
            heartbeat_task.cancel()
            await self.websocket.close()
            self.subscriptions = {}

    @contextmanager
    def log(self, name, folder="furhat"):
        logger = get_logger(name, folder, True)
        self.custom_loggers.append(logger)
        yield logger
        self.custom_loggers.remove(logger)

    async def send(self, event):
        result = await self.websocket.send(json.dumps(event))

    async def recv(self):
        try:
            while True:
                response = await self.websocket.recv()
                event = json.loads(response)
                name = event.get("event_name")
                if name in self.subscriptions:
                    for queue in self.subscriptions[name]:
                        await queue.put(event)
        except websockets.ConnectionClosed:
            print("Connection closed")
            self.disconnect_event.set()

    async def subscribe(self, name) -> AsyncIterator[Dict]:
        if name not in self.subscriptions:
            event = { "event_name": 'furhatos.event.actions.ActionRealTimeAPISubscribe', "name": name }
            await self.send(event)
            self.subscriptions[name] = []
        queue = asyncio.Queue()
        self.subscriptions[name].append(queue)
        exit_event = asyncio.Event()
        try:
            while True:
                done, pending = await asyncio.wait([queue.get(), self.disconnect_event.wait(), exit_event.wait()], return_when=asyncio.FIRST_COMPLETED)
                if self.disconnect_event.is_set():
                    raise DisconnectError
                yield done.pop().result()
        except asyncio.CancelledError:
            exit_event.set()
            raise
        except GeneratorExit:
            exit_event.set()
            raise
        finally:
            try:
                for task in pending:
                    task.cancel()
                await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
            except UnboundLocalError:
                pass
            print("Subscription closed")
            self.subscriptions[name].remove(queue)


    async def speech(self, return_silence=False) -> AsyncIterator[UserSpeech]:
        gen = self.subscribe("furhatos.event.senses.SenseSpeech")
        try:
            async for event in gen:
                s = UserSpeech(event)
                if s.type == SpeechType.FINAL or s.type == SpeechType.MAXSPEECH or (s.type == SpeechType.SILENCE and return_silence):
                    yield s
        finally:
            gen.aclose()

    async def dyadicSpeech(self) -> AsyncIterator[UserSpeech]:
        async def recv_users():
            gen = self.subscribe("furhatos.event.senses.SenseUsers")
            try:
                async for event in gen:
                    for id_, user in event.get("users").items():
                        self.user_locations[id_] = user["head"]["location"]
            finally:
                gen.aclose()
        task = asyncio.create_task(recv_users())
        await self.send({ "event_name": "furhatos.app.furhatdriver.CustomListen", "endSilTimeout": 500, "infinite": True })
        gen = self.subscribe("furhatos.event.senses.SenseSpeech")
        try:
            prev = None
            num_words_prev = 0
            async for event in gen:
                s = UserSpeech(event)
                location = self.user_locations.get(s.userId)
                if location is not None:
                    if location["x"] < 0:
                        s.role = SpeakerRole.CUSTOMER
                    else:
                        s.role = SpeakerRole.EMPLOYEE
                s.text = ' '.join(s.text.split(' ')[num_words_prev:])
                if s.type == SpeechType.FINAL:
                    yield s
                    prev = None
                    num_words_prev = 0
                elif prev is not None and prev.userId != s.userId:
                    yield prev
                    num_words_prev = len(prev.text.split(' '))
                    prev = s
        except GeneratorExit:
            pass
        finally:
            await self.send({ "event_name": "furhatos.app.furhatdriver.StopListen" })
            gen.aclose()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def say(self, text: str, asynchronous: bool = False, ifSilent: bool = False, abort: bool = False, interruptable: bool = False):
        text = text.replace('&', 'and')
        subscription = self.subscribe("furhatos.event.monitors.MonitorSpeechEnd")
        event = { "event_name": 'furhatos.event.actions.ActionSpeech', "text": text, "asynchronous": asynchronous, "ifSilent": ifSilent, "abort": abort, "yielding": interruptable }
        self.logger.info(str(event))
        for logger in self.custom_loggers:
            logger.info(f"Robot: {text}")
        await self.send(event)
        async for event in subscription:
            break
        subscription.aclose()

    async def listen(self, endSilTimeout: int = 3000, noSpeechTimeout: int = 10000) -> str:
        event = { "event_name": 'furhatos.app.furhatdriver.CustomListen', "endSilTimeout": endSilTimeout, "noSpeechTimeout": noSpeechTimeout}
        await self.send(event)
        async for event in self.speech(return_silence=True):
            self.logger.info(str(event))
            for logger in self.custom_loggers:
                logger.info(f"User: {event.text}")
            return event.text

if __name__ == "__main__":
    async def main():
        async with Furhat("127.0.0.1", 8080).connect() as furhat:
            print("Connected")
            event = { "event_name": 'furhatos.app.furhatdriver.CustomListen', "endSilTimeout": 500, "infinite": True }
            await furhat.send(event)
            async for event in furhat.speech():
                print(event)

    asyncio.run(main())