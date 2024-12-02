import pandas as pd
import plotly.express as px
import json

def get_city_coordinates(uf: str, city_name: str) -> tuple:
    try:
        with open('estados.json', 'r', encoding='utf-8-sig') as estados_file:
            estados = json.load(estados_file)
        
        with open('municipios.json', 'r', encoding='utf-8-sig') as municipios_file:
            municipios = json.load(municipios_file)
        
        uf_code = next((estado['codigo_uf'] for estado in estados if estado['uf'] == uf.upper()), None)
        if not uf_code:
            return None

        city = next((municipio for municipio in municipios if municipio['codigo_uf'] == uf_code and municipio['nome'].lower() == city_name.lower()), None)
        if not city:
            return None

        return city['latitude'], city['longitude']
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")
        return None

clientes_df = pd.read_csv('clientes.csv', sep=',', encoding='utf-8-sig')

coordinates = clientes_df.apply(
    lambda row: get_city_coordinates(row['uf'], row['cidade']), axis=1
)

clientes_df['latitude'] = coordinates.apply(lambda coord: coord[0] if coord else None)
clientes_df['longitude'] = coordinates.apply(lambda coord: coord[1] if coord else None)

valid_clients = clientes_df.dropna(subset=['latitude', 'longitude'])

clientes_df['tot_comprado'] = pd.to_numeric(clientes_df['tot_comprado'], errors='coerce')

clientes_df = clientes_df.dropna(subset=['tot_comprado'])

fig = px.scatter_mapbox(
    valid_clients,
    lat="latitude",
    lon="longitude",
    hover_name="cidade",
    hover_data={
        "cidade": True,
        "uf": True,
        "tot_comprado": ":.2f"
    },
    size="tot_comprado",
    size_max=40,
    color_discrete_sequence=["blue"],
    mapbox_style="open-street-map",
    title="Distribuicao de Clientes no Brasil - 2024"
)

fig.update_traces(
    marker=dict(
        sizeref=500,
        opacity=0.7
    )
)

fig.update_layout(
    mapbox=dict(
        center={"lat": -15.7801, "lon": -47.9292},
        zoom=4.5
    ),
    title_font=dict(size=20),
    margin={"r": 0, "t": 50, "l": 0, "b": 0}
)

fig.write_html("clientes_mapa.html")

fig.show()
