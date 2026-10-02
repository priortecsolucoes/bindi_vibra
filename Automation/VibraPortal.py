"""Passos de automação do Canal de Negócios Vibra (cn.vibraenergia.com.br) via Selenium.

Seletores confirmados via inspeção real do DOM (login SSO Keycloak +
aplicação Angular Material), exceto onde indicado o contrário.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ORDERS_URL = "https://cn.vibraenergia.com.br/consultar-pedidos/#/meus-pedidos"

DEFAULT_TIMEOUT = 30
MFA_POLL_SECONDS = 5

ORDER_NUMBER_SELECTOR = "td.mat-column-numeroPedido span.numero-pedido-selecionado"
PRODUCT_ROWS_SELECTOR = "app-lista-produtos table.tabela-lista-produtos tbody tr"

# Ícones Material exibidos à esquerda de cada produto no detalhe do pedido.
APPROVED_ICON_TEXT = "delete"
BLOCKED_ICON_TEXT = "do_disturb_alt"


@dataclass
class OrderItem:
    """Um produto de um pedido, como aparece na tela de detalhe."""

    order_number: str
    order_status: str
    product_name: str
    product_code: str
    base: str
    quantity_liters: float
    pending_quantity_liters: float
    approved: bool


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------
def login(
    driver: webdriver.Chrome,
    username: str,
    password: str,
    mfa_wait_seconds: int,
    fetch_mfa_code: Callable[[], Optional[str]],
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """Abre 'Meus pedidos' (redireciona pro SSO), autentica e espera a lista carregar.
    Se o SSO pedir o código de 2FA (enviado por e-mail), consulta fetch_mfa_code
    (token informado na tela de Unidades do Portal Bindi Log) por até
    mfa_wait_seconds e digita o código assim que ele aparecer."""
    print("[INFO] Acessando o Canal de Negócios Vibra...")
    driver.get(ORDERS_URL)

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR) or d.find_elements(By.ID, "username")
        )
    except TimeoutException as exc:
        raise RuntimeError(
            f"Nem a tela de login nem a lista 'Meus pedidos' apareceram a tempo. URL atual: {driver.current_url}"
        ) from exc

    if driver.find_elements(By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR):
        print("[OK] Sessão do SSO reaproveitada do perfil do bot - login não foi necessário.")
        return

    username_field = driver.find_element(By.ID, "username")
    username_field.clear()
    username_field.send_keys(username)
    password_field = driver.find_element(By.ID, "password")
    password_field.clear()
    password_field.send_keys(password)
    driver.find_element(By.ID, "loginBt").click()

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR) or _is_mfa_screen(d)
        )
    except TimeoutException as exc:
        raise RuntimeError(
            "Login não confirmado: a lista 'Meus pedidos' não carregou. "
            f"Verifique usuário/senha. URL atual: {driver.current_url}"
        ) from exc

    if _is_mfa_screen(driver):
        print(
            "[AVISO] Autenticação em 2 fatores: informe o código recebido por e-mail no campo "
            f"'Token Login Dist.' da unidade, na tela de Unidades do portal. Aguardando até {mfa_wait_seconds}s..."
        )
        typed_codes: List[str] = []
        try:
            WebDriverWait(driver, mfa_wait_seconds, poll_frequency=MFA_POLL_SECONDS).until(
                lambda d: _try_mfa_code(d, fetch_mfa_code, typed_codes)
                or d.find_elements(By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR)
            )
        except TimeoutException as exc:
            detail = "código informado não foi aceito" if typed_codes else "código não informado no portal"
            raise RuntimeError(f"Autenticação em 2 fatores não concluída em {mfa_wait_seconds}s ({detail}).") from exc

    print("[OK] Login realizado com sucesso.")


def _try_mfa_code(driver: webdriver.Chrome, fetch_mfa_code: Callable[[], Optional[str]], typed_codes: List[str]) -> bool:
    """Digita na tela de 2FA um código novo vindo do portal. Sempre devolve
    False - quem encerra a espera é a lista de pedidos carregando."""
    if not _is_mfa_screen(driver):
        return False
    try:
        code = fetch_mfa_code()
    except Exception as exc:  # noqa: BLE001 - falha momentânea do portal não pode abortar a espera
        print(f"[AVISO] Falha ao consultar o token no portal (tentando de novo): {exc}")
        return False
    if not code or code in typed_codes:
        return False

    # Seletor do campo de código não confirmado via DOM - usa o primeiro input visível da tela.
    inputs = [
        field for field in driver.find_elements(By.CSS_SELECTOR, "form input:not([type=hidden])")
        if field.is_displayed() and field.is_enabled()
    ]
    if not inputs:
        print("[ERRO] Campo do código de 2FA não encontrado na tela.")
        return False
    inputs[0].clear()
    inputs[0].send_keys(code, Keys.ENTER)
    typed_codes.append(code)
    print("[INFO] Token informado no portal digitado na tela de 2FA.")
    return False


def _is_mfa_screen(driver: webdriver.Chrome) -> bool:
    return "Autenticação em 2 fatores" in driver.find_element(By.TAG_NAME, "body").text


def _wait_orders_list(driver: webdriver.Chrome, timeout: int) -> None:
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR))
    )


# --------------------------------------------------------------------------
# Lista 'Meus pedidos'
# --------------------------------------------------------------------------
def list_order_numbers(driver: webdriver.Chrome) -> List[str]:
    """Números de pedido visíveis na lista (filtro padrão do portal: últimos 30 dias).

    NOTA: paginação/rolagem infinita da lista ainda não foi validada no DOM
    real - só os pedidos já renderizados na tela são coletados.
    """
    spans = driver.find_elements(By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR)
    order_numbers = [span.text.strip() for span in spans if span.text.strip()]
    # Deduplica mantendo a ordem da tela.
    return list(dict.fromkeys(order_numbers))


def open_order_detail(driver: webdriver.Chrome, order_number: str, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Clica no número do pedido na lista 'Meus pedidos' (a lista precisa estar aberta)."""
    link = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//span[contains(@class,'numero-pedido-selecionado') "
                f"and normalize-space()='{order_number}']",
            )
        )
    )
    # Clique via JS: o clique nativo é interceptado por células vizinhas da linha (layout responsivo).
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", link)

    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, PRODUCT_ROWS_SELECTOR))
        )
    except TimeoutException as exc:
        raise RuntimeError(
            f"Detalhe do pedido {order_number} não carregou a lista de produtos."
        ) from exc


def back_to_orders_list(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> None:
    driver.get(ORDERS_URL)
    _wait_orders_list(driver, timeout)


# --------------------------------------------------------------------------
# Detalhe do pedido
# --------------------------------------------------------------------------
def extract_order_items(driver: webdriver.Chrome, order_number: str) -> List[OrderItem]:
    """Lê os produtos do detalhe do pedido.

    Colunas: [Produto(s), Base, Prazo, Qtd (L), Qtd pendente (L),
    Preço unitário, Valor total]. Ícone de lixeira = aprovado; ícone de
    bloqueio = não aprovado (a linha bloqueada também traz a lixeira,
    desabilitada - por isso o bloqueio é checado primeiro).
    """
    order_status = _read_order_status(driver)

    items: List[OrderItem] = []
    for row in driver.find_elements(By.CSS_SELECTOR, PRODUCT_ROWS_SELECTOR):
        title = row.find_elements(By.CSS_SELECTOR, "div.title-produto")
        if not title:
            continue

        cells = row.find_elements(By.XPATH, "./td")
        if len(cells) < 5:
            raise RuntimeError(
                f"Pedido {order_number}: linha de produto com {len(cells)} coluna(s), esperado ao menos 5."
            )

        product_name = title[0].find_element(By.TAG_NAME, "strong").text.strip()
        product_code = (
            title[0].find_element(By.CSS_SELECTOR, "span.codigo-produto").text.replace("COD:", "").strip()
        )

        items.append(
            OrderItem(
                order_number=order_number,
                order_status=order_status,
                product_name=product_name,
                product_code=product_code,
                base=cells[1].text.strip(),
                quantity_liters=_parse_liters(cells[3].text),
                pending_quantity_liters=_parse_liters(cells[4].text),
                approved=_is_approved(row, order_number, product_name),
            )
        )

    if not items:
        raise RuntimeError(f"Pedido {order_number}: nenhum produto encontrado na tela de detalhe.")
    return items


def _is_approved(row, order_number: str, product_name: str) -> bool:
    icon_texts = [icon.text.strip() for icon in row.find_elements(By.CSS_SELECTOR, "div.nome-imagem-codigo i")]
    if BLOCKED_ICON_TEXT in icon_texts:
        return False
    if APPROVED_ICON_TEXT in icon_texts:
        return True
    raise RuntimeError(
        f"Pedido {order_number}/{product_name}: ícone de situação não reconhecido ({icon_texts})."
    )


def _read_order_status(driver: webdriver.Chrome) -> str:
    """Status geral do pedido (ex.: 'Parcialmente Bloqueado').

    NOTA: seletor ainda não confirmado via DOM real - busca o valor abaixo
    do rótulo 'Status' no cabeçalho do detalhe. Vazio se não encontrar.
    """
    candidates = driver.find_elements(
        By.XPATH,
        "//*[normalize-space(text())='Status']/following-sibling::*[1]",
    )
    if not candidates:
        return ""
    # O badge traz o texto do ícone Material ('info') numa linha antes do status.
    lines = [line.strip() for line in candidates[0].text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _parse_liters(raw: str) -> float:
    """'10.000' ou '3.000,50' (pt-BR) -> float."""
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise RuntimeError(f"Quantidade (L) inválida na tela de detalhe: {raw!r}") from exc
