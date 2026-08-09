"""The job passed from the command bot to the reporter, and the queue between them."""
import asyncio
from dataclasses import dataclass


@dataclass
class ReportJob:
    steam_id64: int
    steam_name: str
    server_name: str
    # Where to report back to, so the worker can answer the right person.
    requester_id: int
    channel_id: int


# Single shared queue. Both clients live in one process, so this needs no IPC.
queue: "asyncio.Queue[ReportJob]" = asyncio.Queue()
