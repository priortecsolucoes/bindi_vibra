"""LogModule — único módulo que persiste o resultado local da conferência.
Mantém o CSV de saída aberto durante toda a execução. Fecha no EndModule."""

import csv
from typing import Optional

from Automation.VibraPortal import OrderItem

FIELDNAMES = [
    "order_number", "distributor_order_number", "station_name", "product_name",
    "requested_liters", "vibra_quantity_liters", "vibra_pending_liters", "vibra_order_status",
    "situation",
]


class LogModule:
    def __init__(self, output_path: str = "pedidos_vibra.csv") -> None:
        self._output_path = output_path
        self._file = open(output_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()
        self._row_count = 0

    def write_comparison(self, portal_item: Optional[dict], vibra_item: Optional[OrderItem], situation: str) -> None:
        portal_item = portal_item or {}
        self._writer.writerow(
            {
                "order_number": portal_item.get("orderNumber", ""),
                "distributor_order_number": portal_item.get("distributorOrderNumber")
                or (vibra_item.order_number if vibra_item else ""),
                "station_name": portal_item.get("stationName", ""),
                "product_name": portal_item.get("productName") or (vibra_item.product_name if vibra_item else ""),
                "requested_liters": portal_item["requestedQtyM3"] * 1000 if "requestedQtyM3" in portal_item else "",
                "vibra_quantity_liters": vibra_item.quantity_liters if vibra_item else "",
                "vibra_pending_liters": vibra_item.pending_quantity_liters if vibra_item else "",
                "vibra_order_status": vibra_item.order_status if vibra_item else "",
                "situation": situation,
            }
        )
        self._file.flush()
        self._row_count += 1

    def close(self) -> None:
        self._file.close()
        print(f"[OK] {self._row_count} item(ns) gravado(s) em {self._output_path}")
