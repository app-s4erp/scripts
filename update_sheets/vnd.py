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
    t."dataLimite"::date "ultimoContato"
FROM
    contas c
    LEFT JOIN tarefas t ON (t.id = c."idTarefaUltLigacao")
    LEFT JOIN usuarios u ON (t."criadoPor" = u.id)
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
    t."dataLimite"::date "ultimoContato"
FROM
    contas c
    LEFT JOIN tarefas t ON (t.id = c."idTarefaUltLigacao")
    LEFT JOIN usuarios u ON (t."criadoPor" = u.id)
WHERE
    c."idEmpresa" = 1
    AND c.deleted = 'N'
    AND c."tipoConta" ILIKE '%Cliente%'
    AND c."idContaVendedor" <> {vendedor_id}
    AND t."criadoPor" = {vendedor_id};
"""

ligacoes_query_template = """
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
    AND t."dataLimite" >= '2024-06-01'
    AND t."criadoPor" = {vendedor_id};
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
