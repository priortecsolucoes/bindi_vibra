"""PROCESS — para cada unidade com itens pendentes: login no Canal de Negócios
Vibra com o usuário/senha da unidade (código 2FA lido do e-mail ou do portal), abre cada
pedido pendente na lista 'Meus pedidos', compara cada item do Portal Bindi Log
com o produto correspondente na Vibra (autorizado total/parcial ou bloqueado)
e reporta a situação ao portal. Erro numa unidade ou num pedido não interrompe os demais."""

import os
from typing import Dict, List, Optional

from Automation.VibraPortal import (
    OrderItem,
    back_to_orders_list,
    extract_order_items,
    go_home,
    is_invoiced_status,
    list_order_numbers,
    login,
    open_order_detail,
    open_orders_list,
    read_current_company,
    switch_to_next_company,
)
from Framework.InitModule import BotConfig
from Log.LogModule import LogModule
from Utils.DriverFactory import create_driver, load_cookies, save_cookies
from Utils.PortalClient import clear_station_token, fetch_station_login, report_item_situations

COOKIES_PATH_TEMPLATE = "vibra_cookies_{station_id}.json"
QTY_EPSILON_LITERS = 1.0

SITUATION_TOTAL = "AUTORIZADO TOTAL"
SITUATION_PARTIAL = "AUTORIZADO PARCIAL"
SITUATION_BLOCKED = "BLOQUEADO"
SITUATION_INVOICED = "FATURADO"
SITUATION_NOT_IN_VIBRA = "NAO ENCONTRADO NA VIBRA"


def process_items(pending_items: List[dict], config: BotConfig, log_module: LogModule) -> None:
    # Sem item pendente não há o que checar - abrir o navegador (e disparar
    # mais um código de 2FA por e-mail) seria execução desperdiçada.
    if not pending_items:
        print("[INFO] Nenhum item pendente no Portal Bindi Log - não abrindo o navegador.")
        return

    # Cada unidade tem seu próprio login na Vibra, e 'Meus pedidos' só mostra
    # os pedidos daquele login.
    items_by_station: Dict[int, List[dict]] = {}
    for item in pending_items:
        items_by_station.setdefault(item["stationId"], []).append(item)

    situations_to_report: List[dict] = []
    for station_id, station_items in items_by_station.items():
        print("=" * 55)
        station_label = station_items[0].get("stationName") or f"id {station_id}"
        print(f"[INFO] Unidade {station_label}: {len(station_items)} item(ns) pendente(s).")
        try:
            situations_to_report.extend(_process_station(station_id, station_items, config, log_module))
        except Exception as exc:  # noqa: BLE001 - erro numa unidade não pode parar as demais
            print(f"[ERRO] Falha ao processar a unidade {station_label}: {exc}")

    _report_situations(situations_to_report, config)


def _process_station(station_id: int, station_items: List[dict], config: BotConfig, log_module: LogModule) -> List[dict]:
    station_login = fetch_station_login(config.portal_api_url, config.portal_api_token, station_id)
    username = station_login.get("username")
    password = station_login.get("password")
    if not username or not password:
        if not config.default_username or not config.default_password:
            raise RuntimeError(
                "usuário/senha de login na Vibra não cadastrados - preencha 'Usuário Login Dist.' e "
                "'Senha Login Dist.' na tela de Unidades do portal, ou VIBRA_USUARIO/VIBRA_SENHA no .env."
            )
        print("[INFO] Unidade sem login cadastrado no portal - usando VIBRA_USUARIO/VIBRA_SENHA do .env.")
        username, password = config.default_username, config.default_password
    # Código antigo (já usado ou expirado) não pode ser digitado no login novo.
    clear_station_token(config.portal_api_url, config.portal_api_token, station_id)

    def fetch_mfa_code() -> Optional[str]:
        return fetch_station_login(config.portal_api_url, config.portal_api_token, station_id).get("token")

    items_by_order: Dict[str, List[dict]] = {}
    for item in station_items:
        items_by_order.setdefault(item["distributorOrderNumber"], []).append(item)

    # Perfil e cookies separados por unidade: a sessão do SSO de um login não
    # pode ser reaproveitada por outra unidade.
    cookies_path = COOKIES_PATH_TEMPLATE.format(station_id=station_id)
    driver = create_driver(
        headless=config.headless,
        user_data_dir=os.path.join(config.chrome_user_data_dir, f"station_{station_id}"),
        profile_directory=config.chrome_profile_directory,
        user_agent=config.chrome_user_agent,
        window_size=config.chrome_window_size,
        chrome_binary_path=config.chrome_binary_path,
    )

    logged_in = False
    to_report: List[dict] = []
    try:
        load_cookies(driver, cookies_path)
        login(
            driver,
            username,
            password,
            config.mfa_wait_seconds,
            fetch_mfa_code,
            token_api_url=config.token_api_url,
            token_api_token=config.token_api_token,
            token_timeout_seconds=config.token_timeout_seconds,
        )
        logged_in = True
        save_cookies(driver, cookies_path)
        open_orders_list(driver)

        # Um login enxerga vários postos do grupo, mas a lista só mostra os
        # pedidos do posto ativo: pedido não achado fica pendente para o próximo posto.
        pending_orders = dict(items_by_order)
        visited_companies = [read_current_company(driver)]
        while True:
            company = visited_companies[-1]
            print("-" * 55)
            print(f"[INFO] Empresa ativa na Vibra: {company}")
            _process_listed_orders(driver, company, pending_orders, to_report, log_module)
            if not pending_orders:
                break

            print(f"[INFO] {len(pending_orders)} pedido(s) não encontrado(s) em {company} - procurando em outra empresa do grupo.")
            try:
                go_home(driver)
                next_company = switch_to_next_company(driver, visited_companies)
                if next_company is None:
                    break
                visited_companies.append(next_company)
                open_orders_list(driver)
            except Exception as exc:  # noqa: BLE001 - falha na troca não pode descartar o que já foi coletado
                print(f"[ERRO] Falha ao trocar de empresa do grupo (busca encerrada nesta unidade): {exc}")
                break

        for order_number in pending_orders:
            print(
                f"[AVISO] Pedido {order_number} não está na lista 'Meus pedidos' de nenhuma empresa do grupo "
                f"({', '.join(visited_companies)})."
            )
    finally:
        # Só com login confirmado: cookies de uma tentativa falha sobrescreveriam uma sessão boa.
        if logged_in:
            save_cookies(driver, cookies_path)
        try:
            driver.quit()
        except Exception as exc:  # noqa: BLE001 - falha ao encerrar não pode mascarar um erro anterior
            print(f"[AVISO] Falha ao encerrar o Chrome (ignorado): {exc}")

    return to_report


def _process_listed_orders(
    driver, company: str, pending_orders: Dict[str, List[dict]], to_report: List[dict], log_module: LogModule
) -> None:
    """Processa os pedidos pendentes que aparecem na lista da empresa ativa e os
    tira de pending_orders - mesmo com erro no detalhe, para não procurá-los de novo em outra empresa."""
    listed_orders = list_order_numbers(driver)
    found = [order for order in pending_orders if order in listed_orders]
    print(f"[OK] {len(listed_orders)} pedido(s) na lista; {len(found)} pendente(s) encontrado(s) em {company}.")

    for order_number in found:
        portal_items = pending_orders.pop(order_number)
        print("-" * 55)
        try:
            print(f"[INFO] Abrindo pedido {order_number}...")
            open_order_detail(driver, order_number)
            vibra_items = extract_order_items(driver, order_number)
            to_report.extend(_compare_order(portal_items, vibra_items, log_module))
        except Exception as exc:  # noqa: BLE001 - erro por pedido não pode parar o loop
            print(f"[ERRO] Falha ao processar o pedido {order_number}: {exc}")
        finally:
            back_to_orders_list(driver)


def _compare_order(portal_items: List[dict], vibra_items: List[OrderItem], log_module: LogModule) -> List[dict]:
    """Casa cada item do portal com o produto da Vibra pelo nome (case-insensitive)
    e devolve o que deve ser reportado. Itens vindos de PEDIDOS_PATH (sem produto)
    só registram o que a Vibra mostra - não há item do portal para comparar."""
    vibra_by_name = {item.product_name.strip().lower(): item for item in vibra_items}

    if not any(item.get("productName") for item in portal_items):
        for vibra_item in vibra_items:
            situation = "APROVADO" if vibra_item.approved else SITUATION_BLOCKED
            print(f"[INFO] {vibra_item.product_name} | {vibra_item.quantity_liters:,.0f} L | {situation} (sem item no portal)")
            log_module.write_comparison(None, vibra_item, situation)
        return []

    to_report: List[dict] = []
    for portal_item in portal_items:
        vibra_item = vibra_by_name.get(portal_item["productName"].strip().lower())
        situation = _classify(portal_item, vibra_item)
        requested_liters = portal_item["requestedQtyM3"] * 1000
        vibra_liters = f"{vibra_item.quantity_liters:,.0f} L" if vibra_item else "-"
        print(
            f"[{'OK' if vibra_item else 'AVISO'}] Pedido {portal_item['orderNumber']} | "
            f"Unidade {portal_item['stationName']} | {portal_item['productName']} | "
            f"solicitado {requested_liters:,.0f} L | Vibra {vibra_liters} | {situation}"
        )
        log_module.write_comparison(portal_item, vibra_item, situation)

        if vibra_item is not None:
            to_report.append(
                {
                    "distributorOrderNumber": portal_item["distributorOrderNumber"],
                    "productName": portal_item["productName"],
                    "quantityLiters": vibra_item.quantity_liters,
                    "approved": vibra_item.approved,
                    "invoiced": is_invoiced_status(vibra_item.order_status),
                }
            )

    portal_names = {item["productName"].strip().lower() for item in portal_items}
    for name, vibra_item in vibra_by_name.items():
        if name not in portal_names:
            print(f"[AVISO] Produto '{vibra_item.product_name}' está no pedido da Vibra mas não entre os itens pendentes do portal.")
    return to_report


def _classify(portal_item: dict, vibra_item: Optional[OrderItem]) -> str:
    if vibra_item is None:
        return SITUATION_NOT_IN_VIBRA
    if is_invoiced_status(vibra_item.order_status):
        return SITUATION_INVOICED
    if not vibra_item.approved:
        return SITUATION_BLOCKED
    requested_liters = portal_item["requestedQtyM3"] * 1000
    if vibra_item.quantity_liters < requested_liters - QTY_EPSILON_LITERS:
        return SITUATION_PARTIAL
    return SITUATION_TOTAL


def _report_situations(situations: List[dict], config: BotConfig) -> None:
    """Falha aqui não pode derrubar o resultado já coletado e gravado no CSV."""
    print("=" * 55)
    if not situations:
        print("[INFO] Nenhum item a reportar ao Portal Bindi Log.")
        return

    try:
        result = report_item_situations(config.portal_api_url, config.portal_api_token, situations)
        print(f"[OK] {result.get('updated', 0)} item(ns) atualizado(s) no Portal Bindi Log.")
        for entry in result.get("notFound", []):
            print(
                f"[AVISO] {entry.get('distributorOrderNumber')}/{entry.get('productName')}: "
                "não encontrado no Portal Bindi Log."
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERRO] Falha ao reportar a situação dos itens ao Portal Bindi Log: {exc}")
