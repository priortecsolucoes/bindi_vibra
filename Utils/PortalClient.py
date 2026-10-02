"""Cliente HTTP do Portal Bindi Log (integração RPA Vibra). Busca os itens-pedido
pendentes de confirmação na distribuidora e reporta de volta a situação de cada
um. Falha de conexão/autenticação é pré-requisito faltando - erro controlado,
interrompe a execução."""

from typing import List

import requests

from Framework.RPAFrameworkException import RPAFrameworkException

REQUEST_TIMEOUT_SECONDS = 30


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def fetch_pending_items(base_url: str, token: str, days_ahead: int) -> List[dict]:
    """GET /api/rpa/vibra/pendentes - itens-pedido da Vibra já com número de
    pedido na distribuidora e ainda não autorizados, com data de carga entre
    hoje e hoje + days_ahead dias."""
    url = f"{base_url.rstrip('/')}/api/rpa/vibra/pendentes"
    try:
        response = requests.get(
            url, headers=_headers(token), params={"days": days_ahead}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise RPAFrameworkException(f"Falha ao conectar no Portal Bindi Log ({url}): {exc}") from exc

    if response.status_code != 200:
        raise RPAFrameworkException(
            f"Portal Bindi Log recusou a busca de pendências (HTTP {response.status_code}): {response.text[:300]}"
        )

    items = response.json().get("items", [])
    print(f"[OK] {len(items)} item(ns) pendente(s) recebido(s) do Portal Bindi Log.")
    return items


def report_item_situations(base_url: str, token: str, items: List[dict]) -> dict:
    """POST /api/rpa/vibra/situacao - reporta a situação de cada produto
    (distributorOrderNumber, productName, quantityLiters, approved).
    Devolve {"updated": N, "notFound": [...]}."""
    url = f"{base_url.rstrip('/')}/api/rpa/vibra/situacao"
    try:
        response = requests.post(url, headers=_headers(token), json={"items": items}, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RPAFrameworkException(f"Falha ao conectar no Portal Bindi Log ({url}): {exc}") from exc

    if response.status_code not in (200, 400):
        # 400 pode vir com sucesso parcial (ver rota) - só HTTP fora desse
        # conjunto é falha de fato (ex.: 401 token errado, 500 servidor).
        raise RPAFrameworkException(
            f"Portal Bindi Log recusou o relato de situação (HTTP {response.status_code}): {response.text[:300]}"
        )

    return response.json()


def fetch_station_login(base_url: str, token: str, station_id: int) -> dict:
    """GET /api/rpa/vibra/unidades/{id}/login - usuário, senha e token 2FA da
    unidade (cadastro de Unidades). Erro aqui afeta só a unidade - RuntimeError."""
    url = f"{base_url.rstrip('/')}/api/rpa/vibra/unidades/{station_id}/login"
    try:
        response = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha ao conectar no Portal Bindi Log ({url}): {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Portal Bindi Log recusou a leitura do login da unidade {station_id} "
            f"(HTTP {response.status_code}): {response.text[:300]}"
        )
    return response.json()


def clear_station_token(base_url: str, token: str, station_id: int) -> None:
    """DELETE /api/rpa/vibra/unidades/{id}/login - limpa o token 2FA antes de um
    login novo, pra o bot não digitar um código antigo (já usado ou expirado)."""
    url = f"{base_url.rstrip('/')}/api/rpa/vibra/unidades/{station_id}/login"
    try:
        response = requests.delete(url, headers=_headers(token), timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha ao conectar no Portal Bindi Log ({url}): {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Portal Bindi Log recusou a limpeza do token da unidade {station_id} "
            f"(HTTP {response.status_code}): {response.text[:300]}"
        )
