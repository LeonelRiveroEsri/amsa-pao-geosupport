"""
Toolbox SIAS PAO.

Herramientas principales:
- Preparar y publicar actualizaciones de estado SIAS por GPServer.
- Preparar reporte de revision KML/KMZ para nuevas SIAS.
- Insertar SIAS por REST GPServer usando JSON.

El archivo esta disenado para ejecutarse en ArcGIS Pro con arcpy.
"""

# Standard library
import os
import re
import time
import json
from pathlib import Path
from urllib.parse import quote
from datetime import datetime
import xml.etree.ElementTree as ET

# Third-party
import pandas as pd
import requests

# ArcGIS / ArcPy
from arcgis import GIS
from arcgis.geometry import Polygon
import arcpy

# Credenciales y recursos base del portal.
cred = {
    "user": {
        "MLP": "admmlppao"
    },
    "pass": {
        "MLP": "Mlppao2022"
    },
    "url": "https://sig.aminerals.cl/portal/"
}

PORTAL_USER = cred["user"]["MLP"]
PORTAL_PASSWORD = cred["pass"]["MLP"]
PORTAL_URL = cred["url"]

gis = GIS(PORTAL_URL, PORTAL_USER, PORTAL_PASSWORD)
layer = gis.content.get("0783a2e8308e4e6d8c7b9299b37357e0").layers[0]

SHAREPOINT_BASE_URL = "https://aminerals.sharepoint.com/:f:/r"
SHAREPOINT_SITE_PATH = "/sites/SIG_AMSA"
SHAREPOINT_LIBRARY_PATH = "/MLP/PAO/SIG Web/SIAS"

GP_ROOT_URL = "https://sig.aminerals.cl/vector/rest/services/CL_MLP_2050"
GP_JSON_PARAM = "json_entrada"
GP_POLL_SECONDS = 5
GP_MAX_WAIT_SECONDS = 600
GP_FINAL_STATUSES = {
    "esriJobSucceeded",
    "esriJobFailed",
    "esriJobCancelled",
    "esriJobTimedOut"
}

UPDATE_STATUS_GP_SERVICE = "UpdateSiasPaoV2"
UPDATE_STATUS_GP_TOOL = "Update_Estados_GP"
INSERT_SIAS_GP_SERVICE = "InsertSiasGP"
INSERT_SIAS_GP_TOOL = "Insert_SIAS_GP"

UPDATE_STATUS_SUBMIT_URL = (
    f"{GP_ROOT_URL}/{UPDATE_STATUS_GP_SERVICE}/GPServer/"
    f"{UPDATE_STATUS_GP_TOOL}/submitJob"
)
UPDATE_STATUS_JOB_BASE_URL = (
    f"{GP_ROOT_URL}/{UPDATE_STATUS_GP_SERVICE}/GPServer/"
    f"{UPDATE_STATUS_GP_TOOL}/jobs"
)
INSERT_SIAS_SUBMIT_URL = (
    f"{GP_ROOT_URL}/{INSERT_SIAS_GP_SERVICE}/GPServer/"
    f"{INSERT_SIAS_GP_TOOL}/submitJob"
)
INSERT_SIAS_JOB_BASE_URL = (
    f"{GP_ROOT_URL}/{INSERT_SIAS_GP_SERVICE}/GPServer/"
    f"{INSERT_SIAS_GP_TOOL}/jobs"
)

# Feature classes destino SIAS.

fc_wm = os.path.join(
    r"\\amssclgis08.ams.gmams.cl\CL_MLP_PAO",
    "02_FGDB",
    "CL_MLP_PAO_v1.gdb",
    "CL_MLP_PAO_17_SIAS",
    "CL_MLP_PAO_SIAS_PO"
)
fc_utm = os.path.join(
    r"\\amssclgis08.ams.gmams.cl\CL_MLP_PAO",
    "02_FGDB",
    "CL_MLP_PAO_UTM19S_v1.gdb",
    "CL_MLP_PAO_17_SIAS",
    "CL_MLP_PAO_SIAS_PO"
)
fcs = [fc_utm, fc_wm]



# ============================================================
# HELPERS
# ============================================================

def msg(texto):
    """Enviar mensaje informativo a la ventana de geoprocesamiento.

    Parámetros:
    - texto: cualquier objeto que se convertirá a string.
    """
    arcpy.AddMessage(str(texto))

def warn(texto):
    """Enviar advertencia a la ventana de geoprocesamiento."""
    arcpy.AddWarning(str(texto))

def err(texto):
    """Enviar error a la ventana de geoprocesamiento."""
    arcpy.AddError(str(texto))


def validar_error_rest(data, contexto):
    """Levanta RuntimeError si ArcGIS REST devuelve un bloque `error`."""
    if "error" not in data:
        return

    error = data["error"]
    code = error.get("code", "Sin codigo")
    message = error.get("message", "Sin mensaje")
    details = error.get("details", [])
    detalle_txt = "\n".join([str(d) for d in details]) if details else ""

    raise RuntimeError(
        f"{contexto}\n"
        f"Codigo: {code}\n"
        f"Mensaje: {message}\n"
        f"Detalle: {detalle_txt}"
    )


def imprimir_mensajes_gp(job_data):
    """Escribe en ArcGIS Pro los mensajes devueltos por un job GPServer."""
    messages = job_data.get("messages", []) or []

    if not messages:
        msg("El servicio no devolvio mensajes adicionales.")
        return

    msg("Mensajes del servicio remoto:")

    for item in messages:
        msg_type = item.get("type", "")
        description = item.get("description", "")

        if not description:
            continue

        if "error" in msg_type.lower():
            err(f"  [ERROR] {description}")
        elif "warning" in msg_type.lower():
            warn(f"  [ADVERTENCIA] {description}")
        else:
            msg(f"  - {description}")


def obtener_token_portal():
    """Obtiene el token de la conexion GIS activa."""
    token = gis._con.token

    if not token:
        raise RuntimeError("No se pudo obtener token desde la conexion GIS activa.")

    return token


def enviar_submit_job(submit_url, json_payload, contexto):
    """Envia un JSON a un GPServer asincrono y devuelve el jobId."""
    payload = {
        "f": "json",
        "token": obtener_token_portal(),
        GP_JSON_PARAM: json_payload
    }

    try:
        response = requests.post(
            submit_url,
            data=payload,
            timeout=60,
            verify=True
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as ex:
        raise RuntimeError(
            f"No fue posible enviar la solicitud al GPServer.\nDetalle: {ex}"
        )

    try:
        submit_data = response.json()
    except Exception:
        raise RuntimeError(
            "El GPServer respondio, pero la respuesta no es JSON valido.\n"
            f"Respuesta recibida:\n{response.text}"
        )

    validar_error_rest(submit_data, contexto)

    job_id = submit_data.get("jobId")

    if not job_id:
        raise RuntimeError(
            "El GPServer no devolvio un jobId valido.\n"
            f"Respuesta recibida:\n"
            f"{json.dumps(submit_data, indent=4, ensure_ascii=False)}"
        )

    return job_id


def monitorear_job_gp(job_base_url, job_id):
    """Consulta el estado de un job GPServer hasta que finaliza."""
    job_url = f"{job_base_url}/{job_id}"
    start_time = time.time()
    last_status = None

    while True:
        elapsed = time.time() - start_time

        if elapsed > GP_MAX_WAIT_SECONDS:
            raise TimeoutError(
                "El job remoto supero el tiempo maximo de espera "
                f"({GP_MAX_WAIT_SECONDS} segundos). Job ID: {job_id}"
            )

        try:
            status_response = requests.get(
                job_url,
                params={"f": "json", "token": obtener_token_portal()},
                timeout=60,
                verify=True
            )
            status_response.raise_for_status()
        except requests.exceptions.RequestException as ex:
            raise RuntimeError(
                "Error consultando el estado del job remoto.\n"
                f"Job ID: {job_id}\nDetalle: {ex}"
            )

        try:
            job_data = status_response.json()
        except Exception:
            raise RuntimeError(
                "La consulta del job respondio, pero no devolvio JSON valido.\n"
                f"Job ID: {job_id}\nRespuesta recibida:\n{status_response.text}"
            )

        validar_error_rest(job_data, "Error consultando el estado del job remoto.")
        job_status = job_data.get("jobStatus")

        if job_status != last_status:
            msg(f"Estado del job remoto: {job_status}")
            last_status = job_status

        if job_status in GP_FINAL_STATUSES:
            return job_status, job_data

        time.sleep(GP_POLL_SECONDS)


def extraer_total_actualizados(job_data):
    """Obtiene el total de registros actualizados desde mensajes GPServer."""
    for item in job_data.get("messages", []) or []:
        description = item.get("description", "") or ""
        match = re.search(
            r"(\d+)\s+registros?\s+actualizados?",
            description,
            flags=re.IGNORECASE
        )

        if match:
            return int(match.group(1))

    return None


def extraer_resumen_insert(job_data):
    """Obtiene recibidos, insertados, duplicados y fallidos desde mensajes GP."""
    resumen = {
        "recibidos": None,
        "insertados": None,
        "duplicados": None,
        "fallidos": None
    }

    patterns = {
        "recibidos": [
            r"registros\s+recibidos\s*:\s*(\d+)",
            r"(\d+)\s+recibidos"
        ],
        "insertados": [
            r"registros\s+insertados\s*:\s*(\d+)",
            r"(\d+)\s+insertados"
        ],
        "duplicados": [
            r"registros\s+omitidos\s+por\s+duplicado\s*:\s*(\d+)",
            r"(\d+)\s+duplicados"
        ],
        "fallidos": [
            r"registros\s+fallidos\s+por\s+error\s*:\s*(\d+)",
            r"(\d+)\s+fallidos"
        ]
    }

    for item in job_data.get("messages", []) or []:
        text = item.get("description", "") or ""

        for key, regex_list in patterns.items():
            for pattern in regex_list:
                match = re.search(pattern, text, flags=re.IGNORECASE)

                if match:
                    resumen[key] = int(match.group(1))
                    break

    return resumen


def construir_where_id_sia(fc, ids_sia):
    """Construye una clausula SQL IN para el campo texto ID_SIA."""
    ids_limpios = [
        str(id_sia).strip()
        for id_sia in ids_sia
        if id_sia is not None and str(id_sia).strip()
    ]

    if not ids_limpios:
        raise ValueError("No hay ID_SIA validos para construir la consulta.")

    campo = arcpy.AddFieldDelimiters(arcpy.Describe(fc).path, "ID_SIA")
    valores = ", ".join(
        "'" + id_sia.replace("'", "''") + "'"
        for id_sia in ids_limpios
    )

    return f"{campo} IN ({valores})"

# ============================================================
# ACTUALIZAR ID
# ============================================================
def updateSiasJson(json_update):
    if not arcpy.Exists(fcs[0]):
        return msg('Sin acceso a la base de datos.')
    data_update = json.loads(json_update)

    estados_por_id_sia = {
        str(item["ID_SIA"]).strip(): item["Estado"]
        for item in data_update
        if item.get("ID_SIA") is not None
    }

    if not estados_por_id_sia:
        raise ValueError("El JSON no contiene registros validos con ID_SIA.")

    for fc in fcs:
        cnt = 0
        _name = Path(fc).parents[1].name
        query_update = construir_where_id_sia(fc, estados_por_id_sia.keys())

        msg(f'Actualizando GDB: {_name}')
        with arcpy.da.UpdateCursor(fc, ["ID_SIA", "Estado"], query_update) as cursor:
            for row in cursor:
                id_sia = str(row[0]).strip()

                nuevo_estado = estados_por_id_sia.get(id_sia)

                if nuevo_estado is not None:
                    row[1] = nuevo_estado
                    cursor.updateRow(row)
                    cnt +=1
        msg(f'Actualización finalizada: {cnt} registros actualizados')
    
def ExcelUpdate(excel,insert=False):
    """Leer y analizar el Excel de control de SIAS.

    Si `insert` es True, devuelve los registros que no existen en el layer
    y prepara columnas necesarias para la inserción desde ArcGIS Pro.

    Si `insert` es False, compara el Excel contra el contenido del servicio
    para detectar cambios de estado y devuelve un SDF con ID_SIA/Estado
    listo para actualizar en la GDB.
    """

    df = pd.read_excel(excel, sheet_name='SIAs PAO Histórico N°2')
    msg(f'Total de registros: {df.shape[0]}')

    ## Se filtran por estado
    df = df[df['Estado'].isin(['Aprobada','Desmovilizada'])].reset_index(drop=True)
    df['ID'] = df['ID'].astype(str).str.strip()
    msg(f'Total de registros filtrados: {df.shape[0]}')
    ## Se lee el layer del servicio
    sdf = layer.query('1=1',return_geometry=False).sdf
    sdf['ID_SIA'] = sdf['ID_SIA'].astype(str).str.strip()
    ## Se filtran las sias en el layer
    df_inlayer = df[df['ID'].isin(sdf['ID_SIA'])]
    
    if insert:
        df_notlayer = df[~df['ID'].isin(sdf['ID_SIA'])]
        if df_notlayer.empty:
            return df_notlayer
        cols_add = {
            "ID": "ID_SIA",
            "Nombre ": "NOMBRE_CARPETA",
            "EECC": "EECC",
            "Estado": "Estado",
            "Fecha Aprobación":"Fecha_Actualizacion"
        }
        df_notlayer = df_notlayer.rename(columns=cols_add)
        df_notlayer = df_notlayer.loc[:,[c for c in cols_add.values()]].reset_index(drop=True)
        ## Se filtra por fecha
        df_notlayer = df_notlayer[df_notlayer['Fecha_Actualizacion'] > '2025-01-01 00:00:00'].reset_index(drop=True)
        

        url = (
            SHAREPOINT_BASE_URL
            + quote(SHAREPOINT_SITE_PATH, safe="/")
            + quote(SHAREPOINT_LIBRARY_PATH, safe="/")
            + "/"
        )
        df_notlayer['URL'] = url + df_notlayer['ID_SIA']
        df_notlayer['NOMBRE_KMZ'] = 'NOMBRE DEL KMZ'
        return df_notlayer
      
    msg(f'Total en capa de servicio: {df_inlayer.shape[0]}')

    # ------------------------------------------------------------
    # 1) Preparar df_inlayer solo con la clave y el estado nuevo
    # ------------------------------------------------------------

    df_estado_nuevo = (
        df_inlayer[['ID', 'Estado']]
        .copy()
        .rename(columns={
            'ID': 'ID_SIA',
            'Estado': 'estado_nuevo'
        })
    )

    # ------------------------------------------------------------
    # 2) Cruzar contra sdf
    # ------------------------------------------------------------

    sdf_tmp = sdf.merge(
        df_estado_nuevo,
        on='ID_SIA',
        how='left'
    )

    # ------------------------------------------------------------
    # 3) Detectar solo estados modificados
    # ------------------------------------------------------------

    mask_modificados = (
        sdf_tmp['estado_nuevo'].notna() &
        sdf_tmp['Estado'].fillna('') .ne(sdf_tmp['estado_nuevo'].fillna(''))
    )

    # ------------------------------------------------------------
    # 4) Crear sdf solo con los modificados
    # ------------------------------------------------------------

    sdf_modificados = sdf_tmp.loc[mask_modificados].copy()

    # Actualizar estado con el nuevo valor
    sdf_modificados['Estado'] = sdf_modificados['estado_nuevo']

    # Limpiar columna auxiliar
    sdf_modificados = sdf_modificados.drop(columns=['estado_nuevo'])
    sdf_modificados = sdf_modificados.loc[:,['ID_SIA','Estado']] 
    return sdf_modificados
             
def updateSias(excel):
    if not arcpy.Exists(fcs[0]):
        return msg('Sin acceso a la base de datos.')
    sdf_modificados = ExcelUpdate(excel)
    if sdf_modificados.empty:
        return msg('Sin SIAS para actualizar.')
    msg(f"Total modificados: {sdf_modificados.shape[0]}")

    estados_por_id_sia = {
        str(row["ID_SIA"]).strip(): row["Estado"]
        for _, row in sdf_modificados.iterrows()
    }

    for fc in fcs:
        _name = Path(fc).parents[1].name
        query_update = construir_where_id_sia(fc, estados_por_id_sia.keys())

        msg(f'Actualizando gdb --> {_name}')
        msg(query_update)

        cnt = 0
        with arcpy.da.UpdateCursor(fc, ['ID_SIA', 'Estado'], query_update) as cursor:
            for row in cursor:
                id_sia = str(row[0]).strip()
                nuevo_estado = estados_por_id_sia.get(id_sia)

                if nuevo_estado is None:
                    continue

                row[1] = nuevo_estado
                cursor.updateRow(row)
                cnt +=1
        msg(f'Terminado la actualizacion total --> {cnt} registros actualizados')

def updateSiasGp(excel):
    """
    Ejecuta el flujo mixto:
    1. Analiza localmente el Excel en ArcGIS Pro.
    2. Detecta SIAS modificadas.
    3. Envía los cambios como JSON a la GP Tool publicada.
    4. Monitorea el job remoto.
    5. Informa al usuario el resultado final en ArcGIS Pro.
    """

    # ============================================================
    # CONFIGURACIÓN
    # ============================================================

    GP_SUBMIT_URL = UPDATE_STATUS_SUBMIT_URL
    GP_JOB_BASE_URL = UPDATE_STATUS_JOB_BASE_URL

    # ============================================================
    # 1. ANÁLISIS LOCAL DEL EXCEL
    # ============================================================

    msg("Iniciando actualización de estados SIA...")
    msg("Analizando archivo Excel de entrada en ArcGIS Pro...")

    sdf_modificados = ExcelUpdate(excel)

    if sdf_modificados is None or sdf_modificados.empty:
        msg("Proceso finalizado. No se detectaron SIAS para actualizar.")
        return {
            "status": "sin_cambios",
            "registros_enviados": 0,
            "registros_actualizados": 0,
            "job_id": None
        }

    columnas_requeridas = ["ID_SIA", "Estado"]

    for col in columnas_requeridas:
        if col not in sdf_modificados.columns:
            raise ValueError(
                f"La columna requerida '{col}' no existe en el resultado de ExcelUpdate."
            )

    df_envio = sdf_modificados[columnas_requeridas].copy()
    df_envio = df_envio.dropna(subset=["ID_SIA", "Estado"])

    if df_envio.empty:
        msg(
            "Proceso finalizado. Se detectó estructura de cambios, "
            "pero no hay registros válidos con ID_SIA y Estado."
        )
        return {
            "status": "sin_registros_validos",
            "registros_enviados": 0,
            "registros_actualizados": 0,
            "job_id": None
        }

    df_envio["ID_SIA"] = df_envio["ID_SIA"].astype(str).str.strip()
    df_envio["Estado"] = df_envio["Estado"].astype(str)

    total_detectados = len(df_envio)

    msg(f"SIAS modificadas detectadas: {total_detectados}")
    msg("Preparando paquete JSON para actualización remota...")

    records = df_envio.to_dict("records")
    msg(records)

    json_entrada = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":")
    )

    msg("JSON de actualización generado correctamente.")

    # Opcional: mostrar un resumen de los ID_SIA enviados
    ids_preview = df_envio["ID_SIA"].astype(str).tolist()

    if len(ids_preview) <= 10:
        msg(f"ID_SIA enviados: {', '.join(ids_preview)}")
    else:
        msg(
            "ID_SIA enviados: "
            f"{', '.join(ids_preview[:10])} ... "
            f"y {len(ids_preview) - 10} más."
        )

    # ============================================================
    # 2. EJECUTAR JOB REST
    # ============================================================

    msg("Validando sesion y token de ArcGIS...")
    obtener_token_portal()
    msg("Token obtenido correctamente.")

    msg("Enviando solicitud de actualizacion al servicio GPServer...")
    job_id = enviar_submit_job(
        submit_url=GP_SUBMIT_URL,
        json_payload=json_entrada,
        contexto="Error al enviar el job al GPServer."
    )
    msg(f"Job remoto creado correctamente: {job_id}")

    msg("Monitoreando ejecucion remota...")
    job_status, job_data = monitorear_job_gp(GP_JOB_BASE_URL, job_id)

    # ============================================================
    # 3. RESULTADO FINAL
    # ============================================================

    msg("Ejecución remota finalizada. Procesando resultado...")

    imprimir_mensajes_gp(job_data)

    registros_actualizados = extraer_total_actualizados(job_data)

    if registros_actualizados is None:
        registros_actualizados = 0

    if job_status == "esriJobSucceeded":
        msg("Actualización SIA finalizada correctamente.")
        msg(f"Registros enviados al servicio: {total_detectados}")
        msg(f"Registros actualizados por el GPServer: {registros_actualizados}")
        msg(f"Job ID: {job_id}")

        if registros_actualizados != total_detectados:
            msg(
                "Advertencia: la cantidad enviada no coincide exactamente "
                "con la cantidad reportada como actualizada por el servicio."
            )

        return {
            "status": "correcto",
            "job_status": job_status,
            "job_id": job_id,
            "registros_enviados": total_detectados,
            "registros_actualizados": registros_actualizados,
            "json_enviado": json_entrada
        }

    if job_status == "esriJobFailed":
        raise RuntimeError(
            "La actualización remota falló en el GPServer.\n"
            f"Job ID: {job_id}"
        )

    if job_status == "esriJobCancelled":
        raise RuntimeError(
            "La actualización remota fue cancelada.\n"
            f"Job ID: {job_id}"
        )

    if job_status == "esriJobTimedOut":
        raise RuntimeError(
            "La actualización remota superó el tiempo permitido por el servidor.\n"
            f"Job ID: {job_id}"
        )

    raise RuntimeError(
        f"Estado final no reconocido: {job_status}\n"
        f"Job ID: {job_id}"
    )

def generar_reporte_revision_kml(df_notlayer):
    """
    Genera:
    1. Excel editable para que el usuario coloque el path del KML corregido.
    2. HTML interactivo con enlaces SharePoint para revisión.
    """
    output_folder = Path.home() / 'htmlreport'
    
    os.makedirs(output_folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d")

    excel_out = os.path.join(
        output_folder,
        f"plantilla_revision_kml_sias_{timestamp}.xlsx"
    )

    html_out = os.path.join(
        output_folder,
        f"reporte_revision_kml_sias_{timestamp}.html"
    )

    df_reporte = df_notlayer.copy()

    # Asegurar columnas base
    if "PATH_KML_CORREGIDO" not in df_reporte.columns:
        df_reporte["PATH_KML_CORREGIDO"] = ""

    if "APROBADO_INSERT" not in df_reporte.columns:
        df_reporte["APROBADO_INSERT"] = "NO"

    if "OBSERVACION_REVISION" not in df_reporte.columns:
        df_reporte["OBSERVACION_REVISION"] = ""

    if "ESTADO_VALIDACION" not in df_reporte.columns:
        df_reporte["ESTADO_VALIDACION"] = "PENDIENTE"

    if "MENSAJE_VALIDACION" not in df_reporte.columns:
        df_reporte["MENSAJE_VALIDACION"] = ""

    cols_prioritarias = [
        "ID_SIA",
        "NOMBRE_KMZ",
        "URL",
        "PATH_KML_CORREGIDO",
        "APROBADO_INSERT",
        "OBSERVACION_REVISION",
        "ESTADO_VALIDACION",
        "MENSAJE_VALIDACION"
    ]

    cols_finales = [
        col for col in cols_prioritarias if col in df_reporte.columns
    ] + [
        col for col in df_reporte.columns if col not in cols_prioritarias
    ]

    df_reporte = df_reporte[cols_finales]

    # Exportar Excel
    with pd.ExcelWriter(excel_out, engine="openpyxl") as writer:
        df_reporte.to_excel(
            writer,
            sheet_name="Revision_KML",
            index=False
        )

        ws = writer.book["Revision_KML"]
        ws.freeze_panes = "A2"

        for column_cells in ws.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter

            for cell in column_cells:
                value = cell.value
                if value is not None:
                    max_length = max(max_length, len(str(value)))

            ws.column_dimensions[column_letter].width = min(
                max_length + 3,
                60
            )

    # Generar HTML
    total = len(df_reporte)

    rows_html = ""

    for _, row in df_reporte.iterrows():
        id_sia = row.get("ID_SIA", "")
        nombre_kmz = row.get("NOMBRE_KMZ", "PENDIENTE DE IDENTIFICAR")
        url = row.get("URL", "")
        aprobado = row.get("APROBADO_INSERT", "NO")

        link_html = (
            f'<a href="{url}" target="_blank">Abrir SharePoint</a>'
            if pd.notna(url) and str(url).strip()
            else "Sin URL"
        )

        rows_html += f"""
        <tr>
            <td>{id_sia}</td>
            <td>{nombre_kmz}</td>
            <td>{link_html}</td>
            <td>{aprobado}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Reporte revisión KML SIAS</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 24px;
                background: #f5f7fa;
                color: #1f2937;
            }}
            .card {{
                background: white;
                border-radius: 12px;
                padding: 24px;
                box-shadow: 0 4px 16px rgba(0,0,0,0.08);
            }}
            h1 {{
                margin-top: 0;
                color: #003366;
            }}
            .summary {{
                display: flex;
                gap: 16px;
                margin-bottom: 24px;
            }}
            .metric {{
                background: #eef4ff;
                border-left: 5px solid #005eb8;
                padding: 14px 18px;
                border-radius: 8px;
                min-width: 180px;
            }}
            .metric .value {{
                font-size: 28px;
                font-weight: bold;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
            }}
            th {{
                background: #003366;
                color: white;
                text-align: left;
                padding: 10px;
            }}
            td {{
                border-bottom: 1px solid #ddd;
                padding: 10px;
            }}
            tr:hover {{
                background: #f0f7ff;
            }}
            a {{
                color: #005eb8;
                font-weight: bold;
                text-decoration: none;
            }}
            .note {{
                margin-top: 16px;
                padding: 12px;
                background: #fff8e1;
                border-left: 5px solid #f5a400;
                border-radius: 8px;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Reporte de revisión KML/KMZ para carga SIAS</h1>

            <div class="summary">
                <div class="metric">
                    <div>Total pendientes</div>
                    <div class="value">{total}</div>
                </div>
            </div>

            <p>
                Este reporte contiene los registros detectados como pendientes
                de carga en la capa destino. Revise los enlaces de SharePoint,
                descargue/corrija los KML/KMZ y complete el archivo Excel generado
                con el path local del KML corregido.
            </p>

            <table>
                <thead>
                    <tr>
                        <th>ID SIA</th>
                        <th>Nombre KMZ</th>
                        <th>Enlace SharePoint</th>
                        <th>Aprobado Insert</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>

            <div class="note">
                Complete en el Excel la columna <b>PATH_KML_CORREGIDO</b>
                y marque <b>APROBADO_INSERT = SI</b> solo para los registros listos
                para cargar.
            </div>
        </div>
    </body>
    </html>
    """

    with open(html_out, "w", encoding="utf-8") as f:
        f.write(html)

    return {
        "excel": excel_out,
        "html": html_out,
        "total": total
    }

def abrir_archivos_generados(excel_path=None, html_path=None):
    """
    Abre automáticamente el Excel y el HTML generados.
    Funciona en Windows / ArcGIS Pro.
    """

    if excel_path and os.path.exists(excel_path):
        os.startfile(excel_path)
        time.sleep(1)

    if html_path and os.path.exists(html_path):
        os.startfile(html_path)
        
def siasNuevas(excel):
    df_notlayer = ExcelUpdate(excel,True)
    if df_notlayer.empty:
        msg('Sin SIAS nuevas para cargar.')
        return
    resultado_reporte = generar_reporte_revision_kml(df_notlayer)
    excel_out = resultado_reporte["excel"]
    html_out = resultado_reporte["html"]

    abrir_archivos_generados(
        excel_path=excel_out,
        html_path=html_out
    )
            
    
# ============================================================
# Insertar SIAS NUEVAS
# ============================================================  

def preparar_payload_insert_sias(df, poligonos):
    """Construye el payload JSON para la inserción de SIAS.

    - `df` es un DataFrame con las columnas requeridas de atributos.
    - `poligonos` es un dict map de ID_SIA -> geometría JSON.
    Devuelve un string JSON listo para enviar al GPServer.
    """
    import json
    import pandas as pd

    cols_atributos = [
        "ID_SIA",
        "NOMBRE_CARPETA",
        "EECC",
        "Estado",
        "Fecha_Actualizacion",
        "NOMBRE_KMZ"
    ]

    registros = []

    for _, row in df.iterrows():
        id_sia = str(row["ID_SIA"]).strip()
        geom_json = poligonos.get(id_sia)

        if not geom_json:
            continue

        attributes = {}

        for col in cols_atributos:
            value = row.get(col)

            if pd.isna(value):
                value = None
            elif isinstance(value, pd.Timestamp):
                value = value.strftime("%Y-%m-%d")
            else:
                value = str(value)

            attributes[col] = value

        registros.append({
            "attributes": attributes,
            "geometry": geom_json
        })

    return json.dumps(
        registros,
        ensure_ascii=False,
        separators=(",", ":")
    )


def calcular_url_sharepoint_sia(id_sia):
    url_base_sias = (
        SHAREPOINT_BASE_URL
        + quote(SHAREPOINT_SITE_PATH, safe="/")
        + quote(SHAREPOINT_LIBRARY_PATH, safe="/")
        + "/"
    )

    return url_base_sias + quote(str(id_sia).strip(), safe="")


def obtener_ids_sia_existentes(fc, campo_id="ID_SIA"):
    """
    Obtiene los ID_SIA ya existentes en la feature class destino.
    """

    ids_existentes = set()

    if not arcpy.Exists(fc):
        raise RuntimeError(f"No existe la feature class destino: {fc}")

    with arcpy.da.SearchCursor(fc, [campo_id]) as cursor:
        for row in cursor:
            valor = row[0]

            if valor is not None:
                ids_existentes.add(str(valor).strip().upper())

    return ids_existentes


def insertar_sias_desde_json(json_insert, fc):
    """
    Inserta SIAS en la feature class destino usando JSON con:
    - attributes
    - geometry

    Si el ID_SIA ya existe, no lo inserta.
    """

    data = json.loads(json_insert)

    if not data:
        msg("No hay registros para insertar.")
        return {
            "enviados": 0,
            "insertados": 0,
            "duplicados": 0,
            "fallidos": 0,
            "errores": []
        }

    campos = [
        "ID_SIA",
        "NOMBRE_CARPETA",
        "EECC",
        "Estado",
        "Fecha_Actualizacion",
        "NOMBRE_KMZ",
        "URL",
        "SHAPE@"
    ]

    enviados = len(data)
    insertados = 0
    duplicados = 0
    fallidos = 0
    errores = []

    msg(f"Registros recibidos para insertar: {enviados}")
    msg("Consultando ID_SIA existentes en la capa destino...")

    ids_existentes = obtener_ids_sia_existentes(fc, campo_id="ID_SIA")

    msg(f"ID_SIA existentes en destino: {len(ids_existentes)}")
    msg("Iniciando validación e inserción de registros...")

    ids_insertados_en_esta_ejecucion = set()

    with arcpy.da.InsertCursor(fc, campos) as cursor:
        for item in data:
            try:
                attrs = item.get("attributes", {})
                geom_json = item.get("geometry")

                id_sia = attrs.get("ID_SIA")

                if not id_sia:
                    raise ValueError("Registro sin ID_SIA.")

                id_sia_norm = str(id_sia).strip().upper()

                if id_sia_norm in ids_existentes:
                    duplicados += 1

                    arcpy.AddWarning(
                        f"ID_SIA ya existe en destino. No se inserta: {id_sia}"
                    )

                    errores.append({
                        "ID_SIA": id_sia,
                        "estado": "DUPLICADO_DESTINO",
                        "mensaje": "El ID_SIA ya existe en la capa destino."
                    })

                    continue

                if id_sia_norm in ids_insertados_en_esta_ejecucion:
                    duplicados += 1

                    arcpy.AddWarning(
                        f"ID_SIA repetido dentro del mismo envío. No se inserta: {id_sia}"
                    )

                    errores.append({
                        "ID_SIA": id_sia,
                        "estado": "DUPLICADO_ENVIO",
                        "mensaje": "El ID_SIA viene repetido dentro del JSON recibido."
                    })

                    continue

                if not geom_json:
                    raise ValueError(f"Registro {id_sia} sin geometría.")

                geom = arcpy.AsShape(geom_json, True)

                if geom is None:
                    raise ValueError(f"No se pudo crear geometría para ID_SIA {id_sia}.")

                fecha_txt = attrs.get("Fecha_Actualizacion")

                if fecha_txt:
                    fecha = datetime.strptime(str(fecha_txt)[:10], "%Y-%m-%d")
                else:
                    fecha = None

                url = calcular_url_sharepoint_sia(id_sia)

                values = [
                    id_sia,
                    attrs.get("NOMBRE_CARPETA"),
                    attrs.get("EECC"),
                    attrs.get("Estado"),
                    fecha,
                    attrs.get("NOMBRE_KMZ"),
                    url,
                    geom
                ]

                cursor.insertRow(values)

                insertados += 1
                ids_insertados_en_esta_ejecucion.add(id_sia_norm)

                msg(
                    f"Insertado correctamente ID_SIA: {id_sia}"
                )

            except Exception as ex:
                fallidos += 1

                id_sia_error = (
                    item.get("attributes", {}).get("ID_SIA", "SIN_ID")
                )

                errores.append({
                    "ID_SIA": id_sia_error,
                    "estado": "ERROR",
                    "mensaje": str(ex)
                })

                arcpy.AddWarning(
                    f"No se pudo insertar ID_SIA {id_sia_error}: {ex}"
                )

    msg("Proceso de inserción finalizado.")
    msg(f"Registros recibidos: {enviados}")
    msg(f"Registros insertados: {insertados}")
    msg(f"Registros omitidos por duplicado: {duplicados}")
    msg(f"Registros fallidos por error: {fallidos}")

    return {
        "enviados": enviados,
        "insertados": insertados,
        "duplicados": duplicados,
        "fallidos": fallidos,
        "errores": errores
    }

def gp_insertSias(json_insert):
    if not arcpy.Exists(fcs[0]):
        return msg(f'Sin acceso a la base')
    for fc in fcs:
        insertar_sias_desde_json(json_insert,fc)


def parse_kml(kml_file):
    """Parsea un KML y devuelve un `arcgis.geometry.Polygon`.

    Soporta polígonos con coordenadas en el elemento <coordinates>.
    Retorna un objeto `Polygon` con WKID 4326 (WGS84).
    """
    # Parsear el archivo KML
    tree = ET.parse(kml_file)
    root = tree.getroot()
    
    # Obtener el namespace del archivo KML
    namespace = ''
    for elem in root.iter():
        if '}' in elem.tag:
            namespace = elem.tag.split('}')[0] + '}'
            break
    
    if not namespace:
        raise ValueError("No se encontró el namespace en el archivo KML")
    
    # Encontrar todos los elementos de coordenadas dentro de los polígonos
    coordinates = []
    for placemark in root.findall(f'.//{namespace}Placemark'):
        for polygon in placemark.findall(f'.//{namespace}Polygon'):
            for coord in polygon.findall(f'.//{namespace}coordinates'):
                # Las coordenadas están en formato de texto, separar por espacio y luego por coma
                coords_text = coord.text.strip()
                coords = [list(map(float, c.split(','))) for c in coords_text.split()]
                coordinates.append(coords)

    # Crear el polígono
    polygon = Polygon({
        "rings": coordinates,
        "spatialReference": {"wkid": 4326}  # WGS84
    })
    return polygon


def insertSias(excel):
    """
    Flujo mixto:
    - ArcGIS Pro lee Excel revisado.
    - ArcGIS Pro valida los KML locales y genera geometría JSON.
    - ArcGIS Pro envía JSON al GPServer.
    - GPServer inserta en la GDB del servidor.
    - ArcGIS Pro monitorea el job y muestra resumen final.
    """

    # ============================================================
    # CONFIGURACIÓN GP SERVER
    # ============================================================

    GP_SUBMIT_URL = INSERT_SIAS_SUBMIT_URL
    GP_JOB_BASE_URL = INSERT_SIAS_JOB_BASE_URL

    # ============================================================
    # FUNCIONES INTERNAS
    # ============================================================

    def _normalizar_si_no(valor):
        if pd.isna(valor):
            return ""

        return str(valor).strip().upper()

    # ============================================================
    # 1. LEER EXCEL REVISADO
    # ============================================================

    msg("Iniciando proceso de inserción de SIAS...")
    msg("Leyendo Excel revisado...")

    df = pd.read_excel(excel)

    columnas_requeridas = [
        "ID_SIA",
        "NOMBRE_CARPETA",
        "EECC",
        "Estado",
        "Fecha_Actualizacion",
        "NOMBRE_KMZ",
        "PATH_KML_CORREGIDO"
    ]

    for col in columnas_requeridas:
        if col not in df.columns:
            raise ValueError(f"Falta columna requerida en el Excel: {col}")

    if "APROBADO_INSERT" not in df.columns:
        df["APROBADO_INSERT"] = ""

    msg(f"Registros leídos desde Excel: {len(df)}")

    # ============================================================
    # 2. VALIDAR KML Y PARSEAR GEOMETRÍAS
    # ============================================================

    msg("Validando rutas KML y preparando geometrías...")

    poligonos = {}
    validos = 0
    sin_path = 0
    no_existe = 0
    sin_geometria = 0

    for i, c in df.iterrows():
        id_sia = str(c["ID_SIA"]).strip()
        pathkml = c.get("PATH_KML_CORREGIDO")

        if pd.isna(pathkml) or not str(pathkml).strip():
            df.loc[i, "APROBADO_INSERT"] = "NO"
            df.loc[i, "MENSAJE_VALIDACION"] = "PATH_KML_CORREGIDO vacío."
            sin_path += 1
            continue

        pathkml = str(pathkml).strip()

        if not os.path.exists(pathkml):
            df.loc[i, "APROBADO_INSERT"] = "NO"
            df.loc[i, "MENSAJE_VALIDACION"] = f"No existe el archivo: {pathkml}"
            no_existe += 1
            continue

        try:
            poligono = parse_kml(pathkml)

            if not poligono:
                df.loc[i, "APROBADO_INSERT"] = "NO"
                df.loc[i, "MENSAJE_VALIDACION"] = "No se pudo extraer geometría del KML."
                sin_geometria += 1
                continue

            poligonos[id_sia] = poligono
            df.loc[i, "APROBADO_INSERT"] = "SI"
            df.loc[i, "MENSAJE_VALIDACION"] = "KML validado correctamente."
            validos += 1

        except Exception as ex:
            df.loc[i, "APROBADO_INSERT"] = "NO"
            df.loc[i, "MENSAJE_VALIDACION"] = f"Error parseando KML: {ex}"
            sin_geometria += 1

    msg(f"KML válidos para inserción: {validos}")
    msg(f"Registros sin path KML: {sin_path}")
    msg(f"Archivos KML no encontrados: {no_existe}")
    msg(f"KML sin geometría válida o con error: {sin_geometria}")

    df["APROBADO_INSERT"] = df["APROBADO_INSERT"].apply(_normalizar_si_no)

    df_insert = df[df["APROBADO_INSERT"] == "SI"].copy()

    if df_insert.empty:
        msg("Proceso finalizado. No hay registros válidos para insertar.")
        return {
            "status": "sin_datos",
            "recibidos": 0,
            "insertados": 0,
            "duplicados": 0,
            "fallidos": 0,
            "job_id": None
        }

    # ============================================================
    # 3. ARMAR JSON PARA GP TOOL
    # ============================================================

    cols = [
        "ID_SIA",
        "NOMBRE_CARPETA",
        "EECC",
        "Estado",
        "Fecha_Actualizacion",
        "NOMBRE_KMZ"
    ]

    df_insert = df_insert[cols].copy()

    msg(f"Registros que serán enviados al GPServer: {len(df_insert)}")
    msg("Preparando JSON de inserción...")

    json_insert = preparar_payload_insert_sias(
        df=df_insert,
        poligonos=poligonos
    )

    if not json_insert or json_insert == "[]":
        msg("Proceso finalizado. El JSON de inserción quedó vacío.")
        return {
            "status": "json_vacio",
            "recibidos": 0,
            "insertados": 0,
            "duplicados": 0,
            "fallidos": 0,
            "job_id": None
        }

    msg("JSON de inserción generado correctamente.")

    ids_preview = df_insert["ID_SIA"].astype(str).tolist()

    if len(ids_preview) <= 10:
        msg(f"ID_SIA enviados: {', '.join(ids_preview)}")
    else:
        msg(
            "ID_SIA enviados: "
            f"{', '.join(ids_preview[:10])} ... "
            f"y {len(ids_preview) - 10} más."
        )

    # ============================================================
    # 4. EJECUTAR JOB REST
    # ============================================================

    msg("Validando sesion y token de ArcGIS...")
    obtener_token_portal()
    msg("Token obtenido correctamente.")

    msg("Enviando solicitud de insercion al GPServer...")
    job_id = enviar_submit_job(
        submit_url=GP_SUBMIT_URL,
        json_payload=json_insert,
        contexto="Error al enviar el job de insercion al GPServer."
    )
    msg(f"Job remoto creado correctamente: {job_id}")

    msg("Monitoreando ejecucion remota de insercion...")
    job_status, job_data = monitorear_job_gp(GP_JOB_BASE_URL, job_id)

    # ============================================================
    # 5. RESULTADO FINAL
    # ============================================================

    msg("Ejecución remota finalizada. Procesando mensajes del GPServer...")

    imprimir_mensajes_gp(job_data)

    resumen = extraer_resumen_insert(job_data)

    recibidos = resumen.get("recibidos")
    insertados = resumen.get("insertados")
    duplicados = resumen.get("duplicados")
    fallidos = resumen.get("fallidos")

    if recibidos is None:
        recibidos = len(df_insert)

    if insertados is None:
        insertados = 0

    if duplicados is None:
        duplicados = 0

    if fallidos is None:
        fallidos = 0

    if job_status == "esriJobSucceeded":
        msg("Inserción SIAS finalizada correctamente.")
        msg(f"Registros enviados al servicio: {len(df_insert)}")
        msg(f"Registros recibidos por el GPServer: {recibidos}")
        msg(f"Registros insertados: {insertados}")
        msg(f"Registros omitidos por duplicado: {duplicados}")
        msg(f"Registros fallidos: {fallidos}")
        msg(f"Job ID: {job_id}")

        return {
            "status": "correcto",
            "job_status": job_status,
            "job_id": job_id,
            "enviados": len(df_insert),
            "recibidos": recibidos,
            "insertados": insertados,
            "duplicados": duplicados,
            "fallidos": fallidos,
            "job_data": job_data
        }

    if job_status == "esriJobFailed":
        raise RuntimeError(
            "La inserción remota falló en el GPServer.\n"
            f"Job ID: {job_id}"
        )

    if job_status == "esriJobCancelled":
        raise RuntimeError(
            "La inserción remota fue cancelada.\n"
            f"Job ID: {job_id}"
        )

    if job_status == "esriJobTimedOut":
        raise RuntimeError(
            "La inserción remota superó el tiempo permitido por el servidor.\n"
            f"Job ID: {job_id}"
        )

    raise RuntimeError(
        f"Estado final no reconocido: {job_status}\n"
        f"Job ID: {job_id}"
    )

        

class Toolbox(object):
    def __init__(self):
        self.label = "SIAS PAO"
        self.alias = "SIAS_PAO"
        # Las dos primeras herramientas son las candidatas para publicacion REST.
        self.tools = [
            UpdateSiasPaoGP,
            InsertSiasGP,
            UpdateSiasPao,
            ReportSiasPao,
            InsertSiasTool
        ]

class UpdateSiasPaoGP(object):
    def __init__(self):
        self.label = "Update_Estados_GP"
        self.description = (
            "Servicio GP para actualizar estados SIAS desde JSON. "
            "Tambien permite Excel para ejecucion administrativa."
        )

    def getParameterInfo(self):
        param_archivo = arcpy.Parameter(
            displayName="Excel de estados SIAS",
            name="archivo_entrada",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input"
        )
        param_archivo.filter.list = ["xlsx"]
        
        param_json = arcpy.Parameter(
            displayName="JSON de actualizacion",
            name="json_entrada",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        return [param_archivo, param_json]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        try:
            msg("Ejecutando herramienta: actualización de estado SIA...")
            excel = parameters[0].valueAsText
            paramjson = parameters[1].valueAsText
            
            if excel:
                updateSias(excel)
            elif paramjson:
                updateSiasJson(paramjson)
            else:
                raise arcpy.ExecuteError(
                    "Debe ingresar un archivo Excel o un JSON de entrada."
                )

            
            msg("Herramienta finalizada correctamente.")
        except Exception as e:
            err(f"Error en Update_Estados_GP: {e}")
            raise
        
class UpdateSiasPao(object):
    def __init__(self):
        self.label = "Actualizar_Estados_SIAS"
        self.description = (
            "Cliente ArcGIS Pro: detecta cambios en Excel y ejecuta "
            "Update_Estados_GP via REST."
        )

    def getParameterInfo(self):
        param_archivo = arcpy.Parameter(
            displayName="Excel de estados SIAS",
            name="archivo_entrada",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        param_archivo.filter.list = ["xlsx"]
        

        return [param_archivo]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        try:
            msg("Ejecutando herramienta: actualización de estado SIA...")
            excel = parameters[0].valueAsText
            
            
            if excel:
                updateSiasGp(excel)
            
            else:
                raise arcpy.ExecuteError(
                    "Debe ingresar un archivo Excel o un JSON de entrada."
                )

            
            msg("Herramienta finalizada correctamente.")
        except Exception as e:
            err(f"Error en Actualizar_Estados_SIAS: {e}")
            raise
        
class ReportSiasPao(object):
    def __init__(self):
        self.label = "Preparar_Revision_KML"
        self.description = (
            "Genera Excel y HTML de revision para SIAS nuevas antes de insertar."
        )

    def getParameterInfo(self):
        param_archivo = arcpy.Parameter(
            displayName="Excel historico SIAS",
            name="archivo_entrada",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        param_archivo.filter.list = ["xlsx"]
        

        return [param_archivo]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        try:
            msg("Ejecutando herramienta: reporte SIAS para inserción...")
            excel = parameters[0].valueAsText
            
            
            if excel:
                siasNuevas(excel)
            
            else:
                raise arcpy.ExecuteError(
                    "Debe ingresar un archivo Excel."
                )

            
            msg("Herramienta finalizada correctamente.")
        except Exception as e:
            err(f"Error en Preparar_Revision_KML: {e}")
            raise

class InsertSiasGP(object):
    def __init__(self):
        self.label = "Insert_SIAS_GP"
        self.description = "Servicio GP para insertar SIAS desde JSON via REST."

    def getParameterInfo(self):
        
        param_json = arcpy.Parameter(
            displayName="JSON de insercion",
            name="json_entrada",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )

        return [param_json]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        try:
            msg("Ejecutando herramienta: carga SIAS (GP)...")
            paramjson = parameters[0].valueAsText
      
            if paramjson:
                gp_insertSias(paramjson)
            else:
                raise arcpy.ExecuteError(
                    "Debe ingresar un JSON de insercion."
                )

            
            msg("Herramienta finalizada correctamente.")
        except Exception as e:
            err(f"Error en Insert_SIAS_GP: {e}")
            raise
        
class InsertSiasTool(object):
    def __init__(self):
        self.label = "Insertar_SIAS"
        self.description = (
            "Cliente ArcGIS Pro: valida KML locales y ejecuta Insert_SIAS_GP via REST."
        )

    def getParameterInfo(self):
        param_archivo = arcpy.Parameter(
            displayName="Excel de carga KML",
            name="archivo_entrada",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        param_archivo.filter.list = ["xlsx"]
        

        return [param_archivo]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        try:
            msg("Ejecutando herramienta: inserción de SIAS (local)...")
            excel = parameters[0].valueAsText
            
            
            if excel:
                insertSias(excel)
            
            else:
                raise arcpy.ExecuteError(
                    "Debe ingresar un archivo Excel o un JSON de entrada."
                )

            
            msg("Herramienta finalizada correctamente.")
        except Exception as e:
            err(f"Error en Insertar_SIAS: {e}")
            raise
