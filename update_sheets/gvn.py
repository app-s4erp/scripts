import psycopg2
import gspread
import gspread_dataframe as gd
from google.oauth2.service_account import Credentials
import os
import pandas as pd
import time

con = psycopg2.connect(
    host="aws-0-sa-east-1.pooler.supabase.com",
    database="postgres",
    user="postgres.oukgagddzdptfopvzbli",
    password="pRiZw5yp8spJP206"
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
        tr."dataLimite" "dataLigacao",
        tr.descricao "descricaoLigacao",
        tr."criadoPor" "idVendedorLigacao",
        u.nome "nomeVendedorLigacao"
    FROM 
        tarefas tr
    JOIN
        usuarios u ON (tr."criadoPor" = u.id)
    WHERE 
        tr."fkRelativo" = p."idContaCliente" AND
        tr."dataLimite" <= p."dataAprovado" AND
        tr."objetoRelativo" = 'contas' AND
        tr.tipo = 'Ligação' AND
        tr."statusLigacao" = 'Atendida'
    ORDER BY 
        tr."dataLimite" DESC
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
   	t."dataLimite"::date "ultimoContato"
FROM
    contas c
    LEFT JOIN tarefas t ON (t.id = c."idTarefaUltLigacao")
    LEFT JOIN usuarios u ON (t."criadoPor" = u.id)
WHERE
    c."idEmpresa" = 1
    AND c.deleted = 'N'
    AND c."tipoConta" ILIKE '%Cliente%';
"""

ligacoes = """
SELECT
    t.id,
    t."dataLimite",
    t."fkRelativo" "idConta",
    t.titulo,
    c.uf,
    t."tipoLigacao",
    t."nextSteps",
    t."statusLigacao",
    t."criadoPor",
    u.nome,
    t."criadoEm",
    lc."classificacao"
FROM
    tarefas t
JOIN
	usuarios u ON (u.id = t."criadoPor")
JOIN
	contas c ON (c.id = t."fkRelativo")
LEFT JOIN
	ligacoesclassificacao lc ON (lc."idTarefa" = t.id)
WHERE
    t.tipo = 'Ligação'
    AND t."objetoRelativo" = 'contas'
    AND t."idEmpresa" = 1
    AND t."statusLigacao" <> 'Agendada'
    AND t."dataLimite" >= '2024-06-01';
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
