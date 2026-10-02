"""GET_DATA — itens-pedido a conferir no Canal de Negócios: por padrão, os
itens pendentes no Portal Bindi Log (pedido, unidade, produto, quantidade
solicitada); PEDIDOS_PATH (CSV local, colunas 'pedido' e 'unidade_id') é um
override manual para testes, só com o número do pedido e o id da unidade no
portal (de onde vem o login na Vibra). Nunca escreve."""

import csv
from typing import List

from Framework.InitModule import BotConfig
from Framework.RPAFrameworkException import RPAFrameworkException
from Utils.PortalClient import fetch_pending_items


def get_data(config: BotConfig) -> List[dict]:
    """Cada item tem "distributorOrderNumber" e "stationId"; itens do portal
    também trazem "orderNumber", "stationName", "productName" e "requestedQtyM3"."""
    if config.orders_path:
        return _load_from_csv(config.orders_path)

    return fetch_pending_items(config.portal_api_url, config.portal_api_token, config.portal_pending_days)


def _load_from_csv(orders_path: str) -> List[dict]:
    orders: List[dict] = []
    with open(orders_path, newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            order_number = (row.get("pedido") or "").strip()
            station_id = (row.get("unidade_id") or "").strip()
            if not order_number:
                continue
            if not station_id.isdigit():
                raise RPAFrameworkException(
                    f"{orders_path}: pedido {order_number} sem 'unidade_id' válido (id da unidade no portal)."
                )
            orders.append({"distributorOrderNumber": order_number, "stationId": int(station_id)})

    print(f"[OK] {len(orders)} pedido(s) carregado(s) de {orders_path} (override PEDIDOS_PATH).")
    return orders
