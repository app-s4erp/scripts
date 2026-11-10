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

pedidos = """
SELECT 
    p.id,
    p."idContaCliente",
    p."razaoSocial",
    p."idGrupoEconomico",
    p."dataAprovado",
    p."dataFaturamento" :: date,
    p."totalPedido",
    COALESCE(REPLACE(p.frete::text, '.', ','), '0') frete,
    p."idVendedor",
    p."nomeVendedor",
    p.status,
    p."pedidoDeLead",
    t.*,
    p."fretePorConta",
    p."correios",
    p."condicaoPagamento",
    (SELECT mp."tipoMeioPagamento" FROM contasreceber cr JOIN meiopagamento mp ON (mp.id = cr."idFormaRecebimento") WHERE cr."idPedido" = p.id AND cr.deleted = 'N' AND cr.situacao <> 'Cancelada' LIMIT 1) "tipoMeioPagamento"
FROM 
    pedidos p
LEFT JOIN LATERAL (
    SELECT 
        tr.id "idLigacao",
        COALESCE(tr.call_at, tr.scheduled_at) "dataLigacao",
        tr.description "descricaoLigacao",
        tr.initiated_by_user_id "idVendedorLigacao",
        u.nome "nomeVendedorLigacao"
    FROM 
        crm.calls tr
    JOIN
        usuarios u ON (tr.initiated_by_user_id = u.id)
    WHERE 
        tr.account_id = p."idContaCliente" AND
        COALESCE(tr.call_at, tr.scheduled_at) <= p."dataAprovado" AND
        tr.tenant_id = p."idEmpresa" AND tr.deleted_at IS NULL AND tr.answered IS TRUE
    ORDER BY 
        COALESCE(tr.call_at, tr.scheduled_at) DESC, tr.id DESC
    LIMIT 1
) t ON TRUE
WHERE 
    p."dataAprovado" >= '2022-01-01' AND
    p.deleted = 'N' AND
    p."tipoRegistro" = 'P' AND
    p.status NOT IN ('Em aberto', 'Proposta', 'Cancelado') AND
    p."idEmpresa" = 1
ORDER BY 
    p.id;
"""

clientes = """
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
    AND c."tipoConta" ILIKE '%Cliente%';
"""

ligacoes = """
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
    AND COALESCE(t.call_at, t.scheduled_at) >= '2024-06-01';
"""
        
queries_and_sheets = [
    { "sheet": "Ligações", "query": ligacoes },
    { "sheet": "Clientes", "query": clientes }
]

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
    query = item["query"]
    sheet_name = item["sheet"]
    print(sheet_name)
    cur.execute(query)
    rows = cur.fetchall()
    col_names = [desc[0] for desc in cur.description]
    df = pd.DataFrame(rows, columns=col_names)
    sheet = client.open_by_key("1OvhQDbutDPxYJMcR7taZ7g9psbmFeEw56MAuf6Lf8TU").worksheet(sheet_name)
    gd.set_with_dataframe(sheet, df)
    time.sleep(20)

cur.close()
con.close()
