import psycopg2
import gspread
import gspread_dataframe as gd
from google.oauth2.service_account import Credentials
import os
import pandas as pd
import time
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

con = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    database=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)

clientes_query_template = """
SELECT
    c.id,
    c."razaoSocial",
    c."dataPrimeiraCompra",
    c."dataUltimoContato",
    c."dataUltimaCompra",
    c."valorUltimaCompra",
    c."limiteCredito",
    c.telefone,
    c."emailContato",
    c.uf,
    c."idContaVendedor",
    c."nomeVendedor",
    c."tipoConta",
    c.status,
    c."qntPedidosAprov",
    c."dataUltimoContatoBeforePedAprov",
    u.nome "ultimoVendedorQueFezContato",
    COALESCE(t.call_at, t.scheduled_at)::date "ultimoContato"
FROM
    contas c
    LEFT JOIN LATERAL (SELECT cl.* FROM crm.calls cl WHERE cl.account_id = c.id AND cl.tenant_id = c."idEmpresa" AND cl.deleted_at IS NULL ORDER BY COALESCE(cl.call_at, cl.scheduled_at) DESC, cl.id DESC LIMIT 1) t ON TRUE
    LEFT JOIN usuarios u ON (t.initiated_by_user_id = u.id)
WHERE
    c."idEmpresa" = 1
    AND c.deleted = 'N'
    AND c."tipoConta" ILIKE '%Cliente%'
    AND c."idContaVendedor" = {vendedor_id};
"""

contas_ult_ligacao_query_template = """
SELECT
    c.id,
    c."razaoSocial",
    c."dataPrimeiraCompra",
    c."dataUltimoContato",
    c."dataUltimaCompra",
    c."valorUltimaCompra",
    c."limiteCredito",
    c.telefone,
    c."emailContato",
    c.uf,
    c."idContaVendedor",
    c."nomeVendedor",
    c."tipoConta",
    c.status,
    c."qntPedidosAprov",
    c."dataUltimoContatoBeforePedAprov",
    u.nome "ultimoVendedorQueFezContato",
    COALESCE(t.call_at, t.scheduled_at)::date "ultimoContato"
FROM
    contas c
    LEFT JOIN LATERAL (SELECT cl.* FROM crm.calls cl WHERE cl.account_id = c.id AND cl.tenant_id = c."idEmpresa" AND cl.deleted_at IS NULL ORDER BY COALESCE(cl.call_at, cl.scheduled_at) DESC, cl.id DESC LIMIT 1) t ON TRUE
    LEFT JOIN usuarios u ON (t.initiated_by_user_id = u.id)
WHERE
    c."idEmpresa" = 1
    AND c.deleted = 'N'
    AND c."tipoConta" ILIKE '%Cliente%'
    AND c."idContaVendedor" <> {vendedor_id}
    AND t.initiated_by_user_id = {vendedor_id};
"""

ligacoes_query_template = """
SELECT
    t.id,
    COALESCE(t.call_at, t.scheduled_at) "dataLimite",
    t.account_id "idConta",
    t.description titulo,
    c.uf,
    CASE t.call_type WHEN 0 THEN 'Prospecção' WHEN 1 THEN 'Reativação' WHEN 2 THEN 'Nutrição' WHEN 3 THEN 'Recebida' WHEN 4 THEN 'Negociação' WHEN 5 THEN 'Pós-venda' WHEN 6 THEN 'Outros' WHEN 7 THEN 'Pesquisa' WHEN 8 THEN 'Cobrança' END "tipoLigacao",
    (
        SELECT string_agg(
            CASE step WHEN 0 THEN 'Enviar proposta' WHEN 1 THEN 'Enviar catálogo' WHEN 2 THEN 'Enviar WhatsApp' WHEN 3 THEN 'Aguardar retorno' WHEN 4 THEN 'Retornar ligação' WHEN 5 THEN 'Inativar cadastro' WHEN 6 THEN 'Aplicar pesquisa' WHEN 7 THEN 'Opt-out' WHEN 8 THEN 'E-mail marketing' WHEN 9 THEN 'Outros' END,
            ', ' ORDER BY ord
        )
        FROM unnest(t.next_steps) WITH ORDINALITY AS steps(step, ord)
    ) "nextSteps",
    CASE WHEN t.scheduled_at IS NOT NULL AND t.answered IS NULL THEN 'Agendada' WHEN t.answered THEN 'Atendida' ELSE 'Não Atendida' END "statusLigacao",
    t.initiated_by_user_id "criadoPor",
    u.nome,
    t.created_at "criadoEm",
    CASE
        WHEN conta_vendedor."tipoConta" ILIKE '%representante%' THEN 'Representante'
        WHEN c."tipoConta" ILIKE '%Cliente%' THEN 'Interno'
        WHEN c."tipoConta" ILIKE '%Lead%' THEN 'Lead'
        ELSE 'S/ Vendedor'
    END "classificacao"
FROM
    crm.calls t
JOIN
    usuarios u ON (u.id = t.initiated_by_user_id)
JOIN
    contas c ON (c.id = t.account_id)
LEFT JOIN
    usuarios vendedor ON (vendedor.id = c."idContaVendedor")
LEFT JOIN
    contas conta_vendedor ON (conta_vendedor.id = vendedor."idConta")
WHERE
    t.tenant_id = 1 AND t.deleted_at IS NULL
    AND NOT (t.scheduled_at IS NOT NULL AND t.answered IS NULL)
    AND COALESCE(t.call_at, t.scheduled_at) >= '2024-06-01'
    AND t.initiated_by_user_id = {vendedor_id};
"""

queries_and_sheets = [
    {"sheet": "Ligações", "query_template": ligacoes_query_template},
    {"sheet": "Clientes", "query_template": clientes_query_template},
    {"sheet": "Contas Ult Lig", "query_template": contas_ult_ligacao_query_template}
]

vendedores = [
    {"id": 110, "name": "Flávia", "sheet": "1P3HFJI4n2H6AeBujqDxqzRy37KIKPUP6EHI8bsEt4Qg"},
    {"id": 268, "name": "Douglas", "sheet": "1vdRSSv3zNddhGonnViLL7C2ZARuQB7J9lyG0BjGRvN8"}
]

for vendedor in vendedores:
    cur = con.cursor()

    script_dir = os.path.dirname(os.path.abspath(__file__))

    key_path = os.path.join(script_dir, "key.json")

    creds = Credentials.from_service_account_file(
        key_path,
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.file']
    )
    client = gspread.authorize(creds)

    for item in queries_and_sheets:
        query = item["query_template"].format(vendedor_id=vendedor["id"])
        sheet_name = item["sheet"]
        print(sheet_name)
        cur.execute(query)
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]
        df = pd.DataFrame(rows, columns=col_names)
        idSheet = vendedor["sheet"]
        
        try:
            sheet = client.open_by_key(idSheet).worksheet(sheet_name)
            gd.set_with_dataframe(sheet, df)
        except gspread.exceptions.WorksheetNotFound:
            print(f'Aba "{sheet_name}" não encontrada na planilha do vendedor {vendedor["name"]}. Abas disponíveis:')
            spreadsheet = client.open_by_key(idSheet)
            available_sheets = [ws.title for ws in spreadsheet.worksheets()]
            print(available_sheets)
        
        time.sleep(20)

    cur.close()

con.close()
