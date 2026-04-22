import asyncio
from app.infrastructure.scrapers.qualp_scraper import QualPScraper
from app.core.config import get_settings

async def main():
    s = get_settings()
    scraper = QualPScraper(s.qualp_usuario, s.qualp_senha, headless=True)
    await scraper.iniciar_sessao()
    await scraper._page.screenshot(path="outputs/agora.png", full_page=False)
    print("Screenshot salvo em outputs/agora.png")
    await scraper.encerrar_sessao()

asyncio.run(main())
