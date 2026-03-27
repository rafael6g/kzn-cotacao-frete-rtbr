"""
Test_Initialization
Valida se o browser Playwright inicia sem lançar NotImplementedError no Windows.
"""
import asyncio
import sys
import pytest


@pytest.mark.asyncio
async def test_playwright_starts_without_error():
    """
    Garante que async_playwright().start() não lança NotImplementedError.
    Este é o erro que aparece quando o SelectorEventLoop está ativo no Windows.
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()

        result = "SUCESSO"
        motivo = "Browser Chromium iniciou e fechou sem erros"
    except NotImplementedError as e:
        result = "FALHA"
        motivo = f"NotImplementedError — loop de eventos incompatível: {e}"
        pytest.fail(f"[{result}] - Módulo: Scraper - Motivo: {motivo}")
    except Exception as e:
        result = "FALHA"
        motivo = f"{type(e).__name__}: {e}"
        pytest.fail(f"[{result}] - Módulo: Scraper - Motivo: {motivo}")

    print(f"\n[{result}] - Módulo: Scraper - Motivo: {motivo}")


@pytest.mark.asyncio
async def test_event_loop_policy_is_proactor():
    """
    No Windows, confirma que a política ativa é ProactorEventLoop.
    Em Linux/Mac, confirma que o loop padrão está ativo (sem restrição).
    """
    policy = asyncio.get_event_loop_policy()

    if sys.platform == "win32":
        is_proactor = isinstance(policy, asyncio.WindowsProactorEventLoopPolicy)
        result = "SUCESSO" if is_proactor else "FALHA"
        motivo = (
            "WindowsProactorEventLoopPolicy ativa"
            if is_proactor
            else f"Política incorreta: {type(policy).__name__} — Playwright não conseguirá abrir o Chromium"
        )
        assert is_proactor, f"[{result}] - Módulo: Infraestrutura - Motivo: {motivo}"
    else:
        result = "SUCESSO"
        motivo = f"Plataforma {sys.platform} — sem restrição de loop"

    print(f"\n[{result}] - Módulo: Infraestrutura - Motivo: {motivo}")
