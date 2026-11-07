"""TCP forwarder run inside a HANDBOOK task container: 0.0.0.0:<listen> -> 127.0.0.1:<target>.

The task's MCP proxy binds 127.0.0.1 only, so a published container port cannot reach it; this relays the bytes.

  python3 /tmp/tcp_forward.py 8001 8000
"""

import asyncio
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, target: int) -> None:
    try:
        up_r, up_w = await asyncio.open_connection("127.0.0.1", target)
    except OSError:
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, up_w), pipe(up_r, client_w))


async def main(listen: int, target: int) -> None:
    server = await asyncio.start_server(lambda r, w: handle(r, w, target), "0.0.0.0", listen)  # noqa: S104 - forwards a port of the container
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))
