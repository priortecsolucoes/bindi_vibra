# Coding Standards — Priortec / Network2Express

## Role
You are an assistant for Automation + AI application development at Priortec.
This project is **Network2Express**: bot Python que varre pastas de rede do servidor fiscal
da Accountacy Contabilidade, identifica PDFs de obrigações fiscais pelo prefixo do nome,
e os copia (mantendo o nome original) para a **Pasta Express** configurada — sem navegador, sem Selenium.

## Language conventions
- **Code identifiers** (variables, methods, properties, interfaces, type literals) must be in **English**.
- **User-facing strings**, log messages, comments, and `print` output must be in **Portuguese**.

## Casing
- Python: `snake_case` for all identifiers.

## Classes and abstraction
- Create classes and abstractions only when genuinely necessary — not speculatively.
- Prefer flat functions and simple modules for single-responsibility logic.

## Error handling
- Always add proper exception handling so that automated processes fail loudly, not silently.
- Surface errors in Portuguese with enough context to diagnose.

## Comments
- Write comments only when the *why* is non-obvious. Never describe what well-named code already says.

---

## This project (Bindi - Vibra)

### O que é
Bot Python (Selenium) que coleta os pedidos do **Canal de Negócios Vibra**
(`cn.vibraenergia.com.br/consultar-pedidos/#/meus-pedidos`) para a operação da BindiLog: faz
login (SSO Keycloak), lê a lista "Meus pedidos", abre cada pedido e coleta, por produto, nome,
código, base, quantidade (L), quantidade pendente (L) e se o item foi **aprovado** (ícone de
lixeira `delete`) ou **bloqueado** (ícone `do_disturb_alt`).

Integração com o **Portal Bindi Log** (`C:\Priortec\Bindi-PAINEL`), mesmo desenho do agente
Ipiranga (`C:\Priortec\Bind-Rpa`): o bot busca os pedidos pendentes em
`GET /api/rpa/vibra/pendentes` (pedido, unidade, produto, quantidade solicitada), abre só esses
pedidos, classifica cada item (autorizado total/parcial, bloqueado, não encontrado na Vibra —
`ProcessModule._classify`) e reporta em `POST /api/rpa/vibra/situacao`
(`{items: [{distributorOrderNumber, productName, quantityLiters, approved}]}`). O portal grava
`order_item.distributor_status` = `autorizado` (+ `authorized_qty_m3`) ou `bloqueado`; a unidade
vem do próprio pedido no portal (`transport_order.station_id`). O casamento do produto é por nome
na distribuidora (`product_distributor_name` da VIBRA, senão `product.name`). A lista coletada
também vai para `pedidos_vibra.csv`.

**Login por unidade:** cada unidade tem seu próprio login na Vibra. Usuário, senha e o código de
**2FA** (enviado por e-mail pela Vibra) vêm do cadastro de Unidades do portal
(`station.distributor_login_username/password/token`, migração 026 do painel) via
`GET /api/rpa/vibra/unidades/{id}/login`. Unidade sem usuário/senha no portal usa
`VIBRA_USUARIO`/`VIBRA_SENHA` do `.env` (mesmo login do projeto Bindi - Cadastro). Fluxo: o bot limpa o token (`DELETE` na mesma rota),
pede um ticket à **Vibra Token API** (projeto `C:\Priortec\Bindi-Email`, `POST /token/prepare`,
antes de enviar a senha) e faz login; se cair no 2FA, lê o código no Gmail (`GET /token`,
long-poll até `TOKEN_TIMEOUT_S`, padrão 120) e o digita. Se o e-mail não chegar ou o código não for
aceito, consulta a rota do portal a cada 5s até o usuário informar o código no campo
"Token Login Dist." da tela de Unidades (`MFA_WAIT_SECONDS`, padrão 180). `VIBRA_TOKEN_API_URL=0`
desliga a leitura do e-mail; `VIBRA_TOKEN_API_TOKEN` = `API_TOKEN` do serviço no Railway.
Perfil do Chrome (`chrome_profile/station_<id>`) e cookies (`vibra_cookies_<id>.json`) são
separados por unidade, pra reaproveitar a sessão do SSO sem misturar logins.

### Navegação no portal (seletores confirmados via DOM)
```
Login (SSO)        #username, #password, #loginBt
Home               cn.vibraenergia.com.br/home/#/ (a lista não abre mais por URL direta)
Popup Informativos app-informativo-lateral i.md-icons 'close' (fechar antes de usar o menu)
Menu lateral       app-menu-item div.main-item span.titulo — expande com hover;
                   Pedidos > Consultar > Pedidos Enviados
Empresa ativa      div.dados-cliente span.nome (cabeçalho; nome completo no textContent)
Trocar empresa     i.trigger-grupo-empresa → diálogo "Outras empresas do grupo":
                   div.grupo-empresa (div.razao-social span + input[type=radio]),
                   div.footer-grupo-empresa button 'Trocar' / 'Cancelar'
Meus pedidos       td.mat-column-numeroPedido span.numero-pedido-selecionado  (clicável)
Detalhe do pedido  app-lista-produtos table.tabela-lista-produtos tbody tr
                   div.title-produto strong (nome), span.codigo-produto (COD)
                   td: [Produto, Base, Prazo, Qtd (L), Qtd pendente (L), Preço, Total]
                   div.nome-imagem-codigo i: 'delete' = aprovado, 'do_disturb_alt' = bloqueado
```
Não confirmados: paginação da lista "Meus pedidos" e o seletor do Status geral do pedido.

### Stack
Python 3.11+, `selenium`, `python-dotenv`, `requests`. `PEDIDOS_PATH` (opcional) é um CSV com a coluna
`pedido` e `unidade_id` (id da unidade no portal) para restringir a execução a pedidos específicos.

### Estrutura de pastas do projeto
```
├── main.py                          ← orquestrador (INIT → GET_DATA → PROCESS → END)
├── Framework/
│   ├── InitModule.py                ← valida .env, credenciais e pré-requisitos
│   ├── GetDataModule.py             ← pedidos pendentes do Portal Bindi Log (ou PEDIDOS_PATH)
│   ├── ProcessModule.py             ← login → abre cada pedido → compara portal x Vibra → reporta
│   ├── EndModule.py                 ← finalização (fecha o CSV, imprime resumo)
│   └── RPAFrameworkException.py     ← exceção controlada
├── Automation/
│   └── VibraPortal.py               ← passos Selenium do portal Vibra
├── Utils/
│   ├── DriverFactory.py             ← cria o Chrome WebDriver + persiste cookies do SSO
│   ├── PortalClient.py              ← cliente HTTP do Portal Bindi Log (pendências e situação)
│   └── TokenApiClient.py            ← cliente da Vibra Token API (código 2FA lido do Gmail)
├── Log/
│   └── LogModule.py                 ← grava a conferência em pedidos_vibra.csv
├── requirements.txt
├── .env                              ← não versionar
└── .env.example
```

---

## FrameworkRE — como funciona

Padrão **FrameworkRE** adaptado para Python pela Priortec. Pipeline linear de 4 módulos.
**Reutilize este padrão em todos os projetos de automação Priortec.**

### Pipeline: INIT → GET_DATA → PROCESS → END

```
main.py
  └── InitModule.initialize()        # 1. Valida ambiente (falha total se erro)
  └── GetDataModule.get_data()       # 2. Carrega itens; None = processar tudo
  └── ProcessModule.process_items()  # 3. try/except isolado por item
  └── EndModule.finalize()           # 4. sempre executa (finally)
```

### Módulos e responsabilidades

**InitModule** — valida variáveis de ambiente obrigatórias, existência de paths e pré-requisitos.
Levanta `RPAFrameworkException` para falhas que impedem qualquer execução. Nunca abre browser ou
lê dados de negócio aqui.

**GetDataModule** — única responsabilidade: ler a fonte de dados e devolver `list[dict]` ou `None`.
Filtra itens já processados. Nunca escreve.

**ProcessModule** — itera sobre os itens; cada item tem seu próprio `try/except` (erro em um item
não para o loop). Chama `LogModule` para persistir STATUS e RESULTADO. Instancia scanners/copiers
dentro do loop para evitar estado compartilhado.

**EndModule** — executado no `finally` de `Main.run()`. Fecha recursos, imprime resumo.

**RPAFrameworkException** — para erros controlados (configuração errada, pré-requisito faltando).
Esses erros terminam o processo inteiro. Erros de negócio por item usam `Exception` comum.

**LogModule** — único módulo que escreve na planilha (`openpyxl`). Mantém workbook aberto durante
toda a execução. `write_value(row_index, column_name, value)`. Fecha no `EndModule`.

### Regras do FrameworkRE
1. Um módulo, uma responsabilidade.
2. Falha ruidosa: todo `except` loga com contexto antes de relançar ou registrar.
3. Estado isolado por item: instanciar recursos dentro do loop.
4. LogModule é o único que escreve na planilha.
5. Erros em um item não param o pipeline — registram e continuam.

---

## Estilo CLI
- Separadores `"=" * 55` entre clientes.
- Prefixos: `[OK]`, `[INFO]`, `[AVISO]`, `[ERRO]`, `[ERRO Framework]`.
- Não usar `logging` do Python — `print` direto conforme padrão Priortec.

## Deploy
Railway, via `Dockerfile` (Python 3.11-slim + Google Chrome) + `railway.json`
(`cronSchedule: "*/30 * * * *"`, `restartPolicyType: "NEVER"`). Variáveis de ambiente no
dashboard do Railway (nunca no Dockerfile): `PORTAL_API_URL`, `PORTAL_API_TOKEN`,
`VIBRA_TOKEN_API_URL`, `VIBRA_TOKEN_API_TOKEN` (o login na
Vibra vem do cadastro de Unidades). `CHROME_HEADLESS=1` e `SCHEDULE_INTERVAL_MINUTES=0`
já vêm fixos no Dockerfile. Fora do container, `main.py` repete a execução a cada
`SCHEDULE_INTERVAL_MINUTES` (padrão 5; 0 = roda uma vez). No container o perfil/cookies não persistem entre execuções (sem
volume), então cada execução pede um código 2FA novo por unidade.
