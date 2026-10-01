"""GET_DATA — itens-pedido a conferir no Canal de Negócios: por padrão, os
itens pendentes no Portal Bindi Log (pedido, unidade, produto, quantidade
solicitada); PEDIDOS_PATH (CSV local, coluna 'pedido') é um override manual
para testes, só com o número do pedido. Nunca escreve."""

import csv
from typing import List

from Framework.InitModule import BotConfig
from Utils.PortalClient import fetch_pending_items


def get_data(config: BotConfig) -> List[dict]:
    """Cada item tem "distributorOrderNumber"; itens do portal também trazem
    "orderNumber", "stationName", "productName" e "requestedQtyM3"."""
    if config.orders_path:
        return _load_from_csv(config.orders_path)

    return fetch_pending_items(config.portal_api_url, config.portal_api_token, config.portal_pending_days)


def _load_from_csv(orders_path: str) -> List[dict]:
    orders: List[dict] = []
    with open(orders_path, newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            order_number = (row.get("pedido") or "").strip()
            if order_number:
                orders.append({"distributorOrderNumber": order_number})

    print(f"[OK] {len(orders)} pedido(s) carregado(s) de {orders_path} (override PEDIDOS_PATH).")
    return orders
