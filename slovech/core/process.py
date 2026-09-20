"""Bounded media subprocesses; deadlines/cancellation terminate the process group."""

import asyncio
import os
import signal
from pathlib import Path


async def run_process(
    *args: str, timeout: float = 600, file_limit: tuple[Path, int] | None = None
) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )

    async def capture():
        chunks = []
        size = 0
        while chunk := await process.stdout.read(65536):
            size += len(chunk)
            if size > 4_000_000:
                raise RuntimeError("Media process output limit exceeded")
            chunks.append(chunk)
        await process.wait()
        return b"".join(chunks)

    reader = asyncio.create_task(capture())
    try:
        async with asyncio.timeout(timeout):
            while not reader.done():
                if file_limit:
                    prefix, maximum = file_limit
                    size = sum(
                        path.stat().st_size
                        for path in prefix.parent.glob(prefix.name + "*")
                        if path.is_file()
                    )
                    if size > maximum:
                        raise RuntimeError("Media download size limit exceeded")
                await asyncio.wait({reader}, timeout=0.1)
            output = await reader
            if process.returncode:
                raise RuntimeError(f"Media process failed (exit {process.returncode})")
            return output
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        # Drain the pipe after killing: wait() alone can hang on a full stdout buffer.
        await process.communicate()
