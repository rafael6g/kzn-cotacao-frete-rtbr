"""
Limpa as tabelas de operação do Xano (cache, lotes, itens, histórico).
cache_distancias: remove apenas registros com pedagio vazio.
Mantém: configuracao_site.
"""
import asyncio
import httpx
from app.core.config import get_settings

settings = get_settings()
BASE = settings.xano_url

TABELAS = [
    ("/cache_consulta",  "Cache de consultas"),
    ("/item_cotacao",    "Itens de cotação"),
    ("/lote_cotacao",    "Lotes de cotação"),
    ("/historico_excel", "Histórico Excel"),
]


async def limpar_tabela(client: httpx.AsyncClient, endpoint: str, nome: str) -> None:
    url_list = f"{BASE}{endpoint}"
    resp = await client.get(url_list, params={"per_page": 100})
    if resp.status_code != 200:
        print(f"  [ERRO] {nome}: GET retornou {resp.status_code}")
        return

    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])
    total = len(items)

    if total == 0:
        print(f"  {nome}: já vazia")
        return

    deletados = 0
    for item in items:
        id_ = item.get("id")
        if not id_:
            continue
        r = await client.delete(f"{BASE}{endpoint}/{id_}")
        if r.status_code in (200, 204):
            deletados += 1
        else:
            print(f"    [AVISO] DELETE id={id_} → {r.status_code}")

    print(f"  {nome}: {deletados}/{total} registros removidos")


async def limpar_cache_distancias_sem_pedagio(client: httpx.AsyncClient) -> None:
    """Remove apenas registros de cache_distancias onde pedagio está vazio."""
    endpoint = "/cache_distancias"
    resp = await client.get(f"{BASE}{endpoint}", params={"per_page": 500})
    if resp.status_code != 200:
        print(f"  [ERRO] Cache distâncias: GET retornou {resp.status_code}")
        return

    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])

    sem_pedagio = [i for i in items if not i.get("pedagio", "").strip()]
    com_pedagio = len(items) - len(sem_pedagio)

    if not sem_pedagio:
        print(f"  Cache distâncias: nenhum registro sem pedágio ({com_pedagio} mantidos)")
        return

    deletados = 0
    for item in sem_pedagio:
        id_ = item.get("id")
        r = await client.delete(f"{BASE}{endpoint}/{id_}")
        if r.status_code in (200, 204):
            deletados += 1
        else:
            print(f"    [AVISO] DELETE id={id_} → {r.status_code}")

    print(f"  Cache distâncias: {deletados} sem pedágio removidos | {com_pedagio} com pedágio mantidos")


async def main():
    print(f"\nXano: {BASE}")
    print("=" * 50)
    async with httpx.AsyncClient(timeout=30) as client:
        for endpoint, nome in TABELAS:
            await limpar_tabela(client, endpoint, nome)
        await limpar_cache_distancias_sem_pedagio(client)
    print("=" * 50)
    print("Concluído. configuracao_site mantida intacta.")


asyncio.run(main())
