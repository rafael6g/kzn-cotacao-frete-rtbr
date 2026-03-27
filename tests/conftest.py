"""
Configuração global do pytest.
Define a política de loop do asyncio para Windows antes de qualquer teste.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
