import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import dropbox
import os
import glob
import threading
import time
from datetime import datetime
from procesar_datos import analizar_salud_csv

st.set_page_config(page_title="Mi Dashboard de Salud V3.1", layout="wide")

# ==========================================
# CONFIGURACIÓN DE DROPBOX Y RUTAS LOCALES
# ==========================================
CARPETA_DROPBOX_CSV = "/Aplicaciones/Health Auto Export/Health Auto Export/AppleHealthExport"
CARPETA_DROPBOX_FIT = "/Aplicaciones/HealthFitExporter"

DIR_LOCAL_CSV = "datos_locales/csv"
DIR_LOCAL_FIT = "datos_locales/fit"

os.makedirs(DIR_LOCAL_CSV, exist_ok=True)
os.makedirs(DIR_LOCAL_FIT, exist_ok=True)

# TTL de sincronización: 4 horas en segundos
_SYNC_TTL = 14400
# Lock a nivel de módulo: evita que dos hilos lancen la sync a la vez
_sync_lock = threading.Lock()


@st.cache_resource
def _estado_sync():
    """Objeto compartido entre TODAS las sesiones del mismo proceso.
    Almacena el estado de la sincronización con Dropbox."""
    return {
        "terminado": False,
        "hilo_activo": False,
        "ts": None,
        "nuevos": 0,
        "errores": [],
    }


def _crear_cliente_dropbox():
    """Crea el cliente Dropbox con OAuth2 (sin bloquear st.*)."""
    return dropbox.Dropbox(
        app_key=st.secrets["DROPBOX_APP_KEY"],
        app_secret=st.secrets["DROPBOX_APP_SECRET"],
        oauth2_refresh_token=st.secrets["DROPBOX_REFRESH_TOKEN"]
    )


def _sincronizar_carpeta_noblocking(dbx, ruta_dbx, ruta_local, extension, errores):
    """Descarga solo archivos nuevos/modificados. SIN llamadas a st.*.
    Los errores se acumulan en la lista 'errores' para mostrarlos luego."""
    ruta_api = "" if ruta_dbx == "/" else ruta_dbx
    nuevos = 0
    try:
        resultado = dbx.files_list_folder(ruta_api)
        while True:
            for entrada in resultado.entries:
                if not isinstance(entrada, dropbox.files.FileMetadata):
                    continue
                if not entrada.name.endswith(extension):
                    continue
                ruta_destino = os.path.join(ruta_local, entrada.name)
                if os.path.exists(ruta_destino) and os.path.getsize(ruta_destino) == entrada.size:
                    continue
                ruta_tmp = ruta_destino + ".tmp"
                try:
                    dbx.files_download_to_file(ruta_tmp, entrada.path_lower)
                    os.replace(ruta_tmp, ruta_destino)
                    nuevos += 1
                except Exception as e_desc:
                    if os.path.exists(ruta_tmp):
                        os.remove(ruta_tmp)
                    errores.append(f"No se pudo descargar {entrada.name}: {e_desc}")
            if resultado.has_more:
                resultado = dbx.files_list_folder_continue(resultado.cursor)
            else:
                break
    except Exception as e:
        errores.append(f"Error al listar {ruta_dbx}: {e}")
    return nuevos


def _hilo_sync(estado):
    """Corre en un hilo de fondo. Hace todo el I/O de Dropbox sin bloquear
    el hilo principal de Streamlit (que necesita responder a los health checks)."""
    errores = []
    nuevos = 0
    try:
        dbx = _crear_cliente_dropbox()
        nuevos += _sincronizar_carpeta_noblocking(dbx, CARPETA_DROPBOX_CSV, DIR_LOCAL_CSV, ".csv", errores)
        nuevos += _sincronizar_carpeta_noblocking(dbx, CARPETA_DROPBOX_FIT, DIR_LOCAL_FIT, ".csv", errores)
    except Exception as e:
        errores.append(f"Error crítico al conectar con Dropbox: {e}")
    finally:
        estado["nuevos"] = nuevos
        estado["errores"] = errores
        estado["ts"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        estado["terminado"] = True
        estado["hilo_activo"] = False


@st.cache_data(show_spinner=False)
def cargar_datos_locales():
    rutas_csv = sorted(glob.glob(os.path.join(DIR_LOCAL_CSV, "*.csv")))
    ruta_historico = os.path.join(DIR_LOCAL_FIT, "historico_entrenamientos.csv")
    entrenos_data = []
    if os.path.exists(ruta_historico):
        try:
            df_historico = pd.read_csv(ruta_historico)
            entrenos_data = df_historico.to_dict("records")
        except Exception:
            pass
    return rutas_csv, entrenos_data


@st.cache_data(show_spinner=False)
def cargar_y_analizar_salud(rutas_tuple):
    """Cachea el resultado del procesado de CSVs. Recibe tupla (hasheable)
    para que Streamlit pueda usar las rutas como clave de caché."""
    try:
        return analizar_salud_csv(list(rutas_tuple))
    except Exception:
        return pd.DataFrame()


# ==========================================
# CABECERA
# ==========================================
st.title("🏃‍♂️ Dashboard de Salud y Rendimiento")

# ==========================================
# SINCRONIZACIÓN EN SEGUNDO PLANO
# El hilo principal NUNCA bloquea esperando Dropbox.
# Lanza un daemon thread y muestra una pantalla de espera
# que hace st.rerun() cada 3 s hasta que la sync termine.
# Así el servidor siempre responde a los health checks de Streamlit Cloud.
# ==========================================
estado = _estado_sync()

# Comprobar si hay que re-sincronizar por TTL expirado
if estado["terminado"] and estado["ts"]:
    try:
        ts_dt = datetime.strptime(estado["ts"], "%d/%m/%Y %H:%M")
        if (datetime.now() - ts_dt).total_seconds() > _SYNC_TTL:
            estado["terminado"] = False
    except Exception:
        pass

if not estado["terminado"]:
    # Lanzar hilo de fondo si no hay uno activo ya
    with _sync_lock:
        if not estado["hilo_activo"]:
            estado["hilo_activo"] = True
            t = threading.Thread(target=_hilo_sync, args=(estado,), daemon=True)
            t.start()

    # Pantalla de espera — el hilo principal queda libre para health checks
    st.info("🔄 Sincronizando datos con Dropbox en segundo plano... La página se actualizará automáticamente.")
    with st.spinner("Por favor espera unos segundos..."):
        time.sleep(3)
    st.rerun()
    st.stop()

# Sync completada: mostrar errores si los hay (no crashea)
for err in estado.get("errores", []):
    st.warning(f"⚠️ {err}")

# Invalidar caché de datos si hay archivos nuevos
if estado.get("nuevos", 0) > 0 and not st.session_state.get("cache_invalidada"):
    cargar_datos_locales.clear()
    cargar_y_analizar_salud.clear()
    st.session_state["cache_invalidada"] = True
    st.toast(f"✅ ¡{estado['nuevos']} archivos nuevos descargados de Dropbox!")

# Barra lateral: estado de la sync y botón de refresco manual
with st.sidebar:
    st.markdown("### ⚙️ Sincronización")
    if estado.get("ts"):
        st.caption(f"Última sync: {estado['ts']}")
    if st.button("🔄 Forzar re-sincronización"):
        estado["terminado"] = False
        estado["hilo_activo"] = False
        estado["errores"] = []
        cargar_datos_locales.clear()
        cargar_y_analizar_salud.clear()
        st.session_state.pop("cache_invalidada", None)
        st.rerun()
    st.divider()
    st.caption("Datos: Apple Health + Apple Watch Ultra 2")

with st.spinner("Cargando datos históricos... 🚀"):
    archivos_csv_locales, datos_entrenos = cargar_datos_locales()

# ==========================================
# SECCIÓN 1: SALUD, RECUPERACIÓN Y SUEÑO
# ==========================================
st.header("📊 Análisis de Salud General")

if archivos_csv_locales:
    # Usamos cargar_y_analizar_salud (cacheada) en lugar de llamar directamente
    # a analizar_salud_csv, que re-leería todos los CSVs en cada render.
    df_salud = cargar_y_analizar_salud(tuple(archivos_csv_locales))
    
    if not df_salud.empty:
        st.markdown("### 📅 Filtro de Periodo")
        opcion_periodo_salud = st.radio(
            "Selecciona el periodo a analizar:",
            ["Últimos 30 días", "Últimos 3 meses", "Este Año", "Histórico Completo"],
            horizontal=True, key="filtro_salud"
        )
        
        fecha_maxima_salud = df_salud.index.max()
        if opcion_periodo_salud == "Últimos 30 días":
            fecha_filtro_salud = fecha_maxima_salud - pd.Timedelta(days=30)
        elif opcion_periodo_salud == "Últimos 3 meses":
            fecha_filtro_salud = fecha_maxima_salud - pd.Timedelta(days=90)
        elif opcion_periodo_salud == "Este Año":
            fecha_filtro_salud = pd.Timestamp(year=fecha_maxima_salud.year, month=1, day=1)
        else:
            fecha_filtro_salud = df_salud.index.min()
            
        df_salud_filtrado = df_salud[df_salud.index >= fecha_filtro_salud].copy()
        
        inicio_pasado_salud = fecha_filtro_salud - pd.Timedelta(days=365)
        fin_pasado_salud = fecha_maxima_salud - pd.Timedelta(days=365)
        df_salud_pasado = df_salud[(df_salud.index >= inicio_pasado_salud) & (df_salud.index <= fin_pasado_salud)]
        
        # --- Cálculo de métricas principales ---
        def _mean(col): return df_salud_filtrado[col].mean() if col in df_salud_filtrado.columns else 0
        def _mean_p(col): return df_salud_pasado[col].mean() if (not df_salud_pasado.empty and col in df_salud_pasado.columns) else 0

        media_pasos      = _mean('pasos')
        fc_media_global  = _mean('fc_media')
        hrv_medio        = _mean('hrv')
        spo2_medio       = _mean('spo2')
        sueno_medio      = _mean('sueno_total')
        fc_reposo_medio  = _mean('fc_reposo')
        calorias_medio   = _mean('calorias_totales_kcal')
        min_ejercicio    = _mean('minutos_ejercicio')
        vo2max_actual    = df_salud_filtrado['vo2max'].max() if 'vo2max' in df_salud_filtrado.columns else 0

        pasos_pasado     = _mean_p('pasos')
        fc_pasado        = _mean_p('fc_media')
        hrv_pasado       = _mean_p('hrv')
        spo2_pasado      = _mean_p('spo2')
        sueno_pasado     = _mean_p('sueno_total')
        fc_reposo_pasado = _mean_p('fc_reposo')
        calorias_pasado  = _mean_p('calorias_totales_kcal')
        min_ej_pasado    = _mean_p('minutos_ejercicio')

        # --- Fila 1: métricas de recuperación y sueño ---
        st.markdown(f"### ⚖️ Promedios Diarios ({opcion_periodo_salud})")
        c1, c2, c3, c4, c5 = st.columns(5)

        dif_pasos = f"{media_pasos - pasos_pasado:,.0f}" if pasos_pasado > 0 else None
        c1.metric("🚶 Pasos / día", f"{media_pasos:,.0f}", dif_pasos)

        dif_fc = f"{fc_media_global - fc_pasado:.0f} lpm" if fc_pasado > 0 else None
        c2.metric("❤️ FC Media", f"{fc_media_global:.0f} lpm", dif_fc, delta_color="inverse")

        dif_hrv = f"{hrv_medio - hrv_pasado:.0f} ms" if hrv_pasado > 0 else None
        c3.metric("🔋 HRV Medio", f"{hrv_medio:.0f} ms", dif_hrv)

        dif_spo2 = f"{(spo2_medio - spo2_pasado) * 100 if spo2_medio < 1 else (spo2_medio - spo2_pasado):.1f} %" if spo2_pasado > 0 else None
        c4.metric("🩸 SpO2 Promedio", f"{spo2_medio * 100 if spo2_medio < 1 else spo2_medio:.1f} %", dif_spo2)

        dif_sueno = f"{sueno_medio - sueno_pasado:.1f} h" if sueno_pasado > 0 else None
        c5.metric("💤 Sueño / día", f"{sueno_medio:.1f} h", dif_sueno)

        # --- Fila 2: métricas de forma física (solo si hay datos) ---
        metricas_forma = []
        if fc_reposo_medio > 0:
            dif_fcr = f"{fc_reposo_medio - fc_reposo_pasado:.0f} lpm" if fc_reposo_pasado > 0 else None
            metricas_forma.append(("🫀 FC en Reposo", f"{fc_reposo_medio:.0f} lpm", dif_fcr, "inverse"))
        if vo2max_actual > 0:
            metricas_forma.append(("🫁 VO2Max (est.)", f"{vo2max_actual:.1f} ml/kg/min", None, "normal"))
        if calorias_medio > 0:
            dif_cal = f"{calorias_medio - calorias_pasado:,.0f} kcal" if calorias_pasado > 0 else None
            metricas_forma.append(("🔥 Calorías totales", f"{calorias_medio:,.0f} kcal/día", dif_cal, "normal"))
        if min_ejercicio > 0:
            dif_mej = f"{min_ejercicio - min_ej_pasado:.0f} min" if min_ej_pasado > 0 else None
            metricas_forma.append(("⚡ Min. ejercicio", f"{min_ejercicio:.0f} min/día", dif_mej, "normal"))

        if metricas_forma:
            cols_forma = st.columns(len(metricas_forma))
            for col, (label, val, delta, delta_color) in zip(cols_forma, metricas_forma):
                col.metric(label, val, delta, delta_color=delta_color)
            
        st.divider()
        
        st.markdown("### 🚶‍♂️ Evolución de Actividad (Pasos Diarios)")
        if 'pasos' in df_salud_filtrado.columns:
            fig_pasos = go.Figure()
            fig_pasos.add_trace(go.Scatter(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos'], 
                                        mode='lines', name='Pasos Diarios', 
                                        line=dict(color='#636EFA', width=1), 
                                        fill='tozeroy', fillcolor='rgba(99, 110, 250, 0.2)'))
            if 'pasos_tendencia' in df_salud_filtrado.columns:
                fig_pasos.add_trace(go.Scatter(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos_tendencia'], 
                                            mode='lines', name='Media Semanal', 
                                            line=dict(color='#deff9a', width=4)))
            fig_pasos.update_layout(margin=dict(l=0, r=0, t=30, b=0),
                                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_pasos, width='stretch')
            
        st.divider()

        st.markdown("### 📉 Profundización en Tendencias")
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["❤️ Corazón y HRV", "💤 Análisis del Sueño", "🔥 Actividad", "🔀 Correlación", "📈 Forma Física"])

        with tab1:
            col_fc, col_hrv = st.columns(2)
            with col_fc:
                if 'fc_media' in df_salud_filtrado.columns:
                    cols_fc = [c for c in ['fc_media', 'fc_reposo', 'fc_media_tendencia', 'fc_reposo_tendencia'] if c in df_salud_filtrado.columns]
                    colores_fc = {'fc_media': '#FF4B4B', 'fc_reposo': '#FF9B9B',
                                  'fc_media_tendencia': '#8B0000', 'fc_reposo_tendencia': '#CC3333'}
                    fig_fc = go.Figure()
                    estilos = {'fc_media': ('lines', 1, None), 'fc_reposo': ('lines', 1, None),
                               'fc_media_tendencia': ('lines', 3, None), 'fc_reposo_tendencia': ('lines', 3, 'dash')}
                    nombres = {'fc_media': 'FC Media', 'fc_reposo': 'FC Reposo',
                               'fc_media_tendencia': 'Media 7d', 'fc_reposo_tendencia': 'Reposo 7d'}
                    for col in cols_fc:
                        modo, w, dash = estilos[col]
                        ld = dict(color=colores_fc[col], width=w)
                        if dash: ld['dash'] = dash
                        fig_fc.add_trace(go.Scatter(x=df_salud_filtrado.index, y=df_salud_filtrado[col],
                                                    mode=modo, name=nombres[col], line=ld))
                    fig_fc.update_layout(title="FC Media y FC en Reposo",
                                         legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                                         margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_fc, width='stretch')
            with col_hrv:
                if 'hrv' in df_salud_filtrado.columns:
                    fig_hrv = px.line(df_salud_filtrado, x=df_salud_filtrado.index, y=['hrv', 'hrv_tendencia'],
                                      title="Variabilidad (HRV)", color_discrete_sequence=['#00CC96', '#006400'])
                    st.plotly_chart(fig_hrv, width='stretch')

        with tab2:
            if all(col in df_salud_filtrado.columns for col in ['sueno_total', 'sueno_profundo', 'sueno_rem']):
                fig_sueno = go.Figure()
                df_salud_filtrado['sueno_ligero'] = df_salud_filtrado['sueno_total'] - df_salud_filtrado['sueno_profundo'] - df_salud_filtrado['sueno_rem']
                df_salud_filtrado['sueno_ligero'] = df_salud_filtrado['sueno_ligero'].clip(lower=0)
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_profundo'], name='Profundo', marker_color='#1f77b4'))
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_rem'], name='REM', marker_color='#9467bd'))
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_ligero'], name='Ligero', marker_color='#aec7e8'))
                fig_sueno.update_layout(barmode='stack', title="Fases del Sueño por Noches", yaxis_title="Horas")
                st.plotly_chart(fig_sueno, width='stretch')

        with tab3:
            col_pasos, col_ejercicio = st.columns([2, 1])
            with col_pasos:
                if 'pasos' in df_salud_filtrado.columns:
                    fig_pasos_bar = go.Figure()
                    fig_pasos_bar.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos'],
                                                   name='Pasos', marker_color='#636EFA', opacity=0.6))
                    fig_pasos_bar.update_layout(title="Pasos Diarios", margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_pasos_bar, width='stretch')
            with col_ejercicio:
                if 'minutos_ejercicio' in df_salud_filtrado.columns:
                    fig_mej = go.Figure()
                    df_ej = df_salud_filtrado['minutos_ejercicio'].fillna(0)
                    colores_ej = ['#EF553B' if v >= 30 else '#636EFA' for v in df_ej]
                    fig_mej.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_ej,
                                             marker_color=colores_ej, name='Min. ejercicio'))
                    fig_mej.add_hline(y=30, line_dash="dot", line_color="white", annotation_text="Obj. 30min")
                    fig_mej.update_layout(title="Minutos de Ejercicio", margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_mej, width='stretch')

        with tab4:
            st.markdown("**🔍 Cruce de Variables: Descubriendo Causalidades**")
            cols_analisis = [c for c in ['sueno_total', 'sueno_profundo', 'hrv', 'fc_media', 'fc_reposo', 'pasos'] if c in df_salud_filtrado.columns]
            if len(cols_analisis) > 1:
                color_col = 'hrv' if 'hrv' in cols_analisis else cols_analisis[0]
                fig_matrix = px.scatter_matrix(df_salud_filtrado, dimensions=cols_analisis, color=color_col,
                                               title="Matriz de Dependencias (Saturación de color = Recuperación HRV)",
                                               color_continuous_scale="Peach")
                st.plotly_chart(fig_matrix, width='stretch')

        with tab5:
            col_vo2, col_fcr = st.columns(2)
            with col_vo2:
                if 'vo2max' in df_salud_filtrado.columns and df_salud_filtrado['vo2max'].notna().any():
                    df_vo2 = df_salud_filtrado[['vo2max', 'vo2max_tendencia']].dropna(subset=['vo2max'])
                    fig_vo2 = go.Figure()
                    fig_vo2.add_trace(go.Scatter(x=df_vo2.index, y=df_vo2['vo2max'],
                                                 mode='markers', name='VO2Max', marker=dict(color='#deff9a', size=6)))
                    if 'vo2max_tendencia' in df_vo2.columns:
                        fig_vo2.add_trace(go.Scatter(x=df_vo2.index, y=df_vo2['vo2max_tendencia'],
                                                     mode='lines', name='Tendencia 14d', line=dict(color='#00CC96', width=3)))
                    fig_vo2.update_layout(title="VO2Max Estimado (Apple Watch)", yaxis_title="ml/kg/min",
                                          margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_vo2, width='stretch')
                else:
                    st.info("VO2Max no disponible en los datos exportados.")
            with col_fcr:
                if 'fc_reposo' in df_salud_filtrado.columns and df_salud_filtrado['fc_reposo'].notna().any():
                    df_fcr = df_salud_filtrado[['fc_reposo', 'fc_reposo_tendencia']].dropna(subset=['fc_reposo'])
                    fig_fcr = go.Figure()
                    fig_fcr.add_trace(go.Scatter(x=df_fcr.index, y=df_fcr['fc_reposo'],
                                                 mode='lines', name='FC Reposo',
                                                 line=dict(color='#FF9B9B', width=1),
                                                 fill='tozeroy', fillcolor='rgba(255,155,155,0.15)'))
                    if 'fc_reposo_tendencia' in df_fcr.columns:
                        fig_fcr.add_trace(go.Scatter(x=df_fcr.index, y=df_fcr['fc_reposo_tendencia'],
                                                     mode='lines', name='Tendencia 7d',
                                                     line=dict(color='#CC0000', width=3)))
                    fig_fcr.update_layout(title="FC en Reposo (a la baja = mejor forma)",
                                          yaxis_title="lpm", margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_fcr, width='stretch')
                else:
                    st.info("FC en Reposo no disponible en los datos exportados.")

            # Temperatura de muñeca (Apple Watch Ultra 2)
            if 'temp_muneca' in df_salud_filtrado.columns and df_salud_filtrado['temp_muneca'].notna().any():
                st.divider()
                st.markdown("#### 🌡️ Temperatura de Muñeca — Alerta Temprana de Enfermedad")
                st.caption("El Apple Watch Ultra 2 mide la temperatura relativa durante el sueño. "
                           "Una desviación ≥ +0.5°C suele preceder síntomas de enfermedad/infección en 12-24h.")
                df_temp = df_salud_filtrado[['temp_muneca']].dropna()
                fig_temp = go.Figure()
                colores_temp = ['#EF553B' if abs(v) >= 0.5 else '#636EFA' for v in df_temp['temp_muneca']]
                fig_temp.add_trace(go.Bar(x=df_temp.index, y=df_temp['temp_muneca'],
                                          marker_color=colores_temp, name='Desviación Tª'))
                fig_temp.add_hline(y=0.5, line_dash="dot", line_color="#EF553B", annotation_text="Alerta +0.5°C")
                fig_temp.add_hline(y=-0.5, line_dash="dot", line_color="#636EFA")
                fig_temp.update_layout(yaxis_title="Desviación (°C)", margin=dict(l=0, r=0, t=20, b=0))
                st.plotly_chart(fig_temp, width='stretch')
else:
    st.warning("⚠️ No se han encontrado archivos CSV locales.")

st.divider()

# ==========================================
# SECCIÓN 2: ENTRENAMIENTOS (.FIT)
# ==========================================
st.header("🚴‍♂️ Rendimiento y Carga de Entrenamiento")

if datos_entrenos:
    df_entrenos = pd.DataFrame(datos_entrenos)
    df_entrenos['distancia_km'] = pd.to_numeric(df_entrenos['distancia_km'], errors='coerce').fillna(0)
    df_entrenos['duracion_min'] = pd.to_numeric(df_entrenos['duracion_min'], errors='coerce').fillna(0)
    df_entrenos['carga_entreno'] = pd.to_numeric(df_entrenos['carga_entreno'], errors='coerce').fillna(0)
    
    if 'fecha_inicio' in df_entrenos.columns:
        df_entrenos['fecha_inicio'] = pd.to_datetime(df_entrenos['fecha_inicio'], errors='coerce')
        df_entrenos = df_entrenos.dropna(subset=['fecha_inicio']).sort_values('fecha_inicio')
        
        fecha_maxima = df_entrenos['fecha_inicio'].max()
        
        # --- MODELO PREDICTIVO TSB ---
        carga_diaria = df_entrenos.set_index('fecha_inicio').resample('D')['carga_entreno'].sum().fillna(0)
        idx_completo = pd.date_range(start=carga_diaria.index.min(), end=fecha_maxima)
        carga_diaria = carga_diaria.reindex(idx_completo, fill_value=0)
        
        if len(carga_diaria) >= 1:
            atl_actual = carga_diaria.rolling(window=7, min_periods=1).mean().iloc[-1]
            ctl_actual = carga_diaria.rolling(window=42, min_periods=1).mean().iloc[-1]
            ratio_carga = atl_actual / ctl_actual if ctl_actual > 0 else 0
            
            st.markdown("### 🔮 Analítica Predictiva de Lesiones (TSB)")
            col_atl, col_ctl, col_riesgo = st.columns(3)
            col_atl.metric("Fatiga Actual (ATL - 7d)", f"{atl_actual:.0f} pts/día")
            col_ctl.metric("Fitness Asimilado (CTL - 42d)", f"{ctl_actual:.0f} pts/día")
            
            if ratio_carga > 1.5:
                col_riesgo.metric("Estado", "⚠️ RIESGO ALTO", "Peligro de lesión", delta_color="inverse")
            elif ratio_carga > 1.2:
                col_riesgo.metric("Estado", "⚡ SOBRECARGA", "Atención a la recuperación")
            elif ratio_carga >= 0.8:
                col_riesgo.metric("Estado", "✅ ÓPTIMO", "Zonas estables")
            else:
                col_riesgo.metric("Estado", "📉 DESENTRENAMIENTO", "Aumenta la carga", delta_color="inverse")
            
            st.divider()

        # --- TSB HISTÓRICO ---
        st.markdown("### 📊 Evolución de Carga: ATL · CTL · TSB")
        ctl_serie = carga_diaria.rolling(window=42, min_periods=1).mean()
        atl_serie = carga_diaria.rolling(window=7, min_periods=1).mean()
        tsb_serie = ctl_serie - atl_serie

        fig_tsb_hist = go.Figure()
        fig_tsb_hist.add_trace(go.Scatter(x=ctl_serie.index, y=ctl_serie.values,
                                          mode='lines', name='CTL – Fitness (42d)',
                                          line=dict(color='#00CC96', width=2)))
        fig_tsb_hist.add_trace(go.Scatter(x=atl_serie.index, y=atl_serie.values,
                                          mode='lines', name='ATL – Fatiga (7d)',
                                          line=dict(color='#EF553B', width=2)))
        fig_tsb_hist.add_trace(go.Bar(x=tsb_serie.index, y=tsb_serie.values,
                                      name='TSB – Forma',
                                      marker_color=['#00CC96' if v >= 0 else '#EF553B' for v in tsb_serie.values],
                                      opacity=0.5))
        fig_tsb_hist.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.3)
        fig_tsb_hist.update_layout(barmode='overlay',
                                   legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                                   margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_tsb_hist, width='stretch')

        st.divider()

        # --- EVOLUCIÓN DE EFICIENCIA AERÓBICA HISTÓRICA ---
        st.markdown("### 📈 Evolución del Índice de Eficiencia Aeróbica")
        df_running = df_entrenos[df_entrenos['deporte'] == 'running'].copy()
        if not df_running.empty and 'eficiencia_aerobica' in df_running.columns:
            fig_ef = px.scatter(df_running, x='fecha_inicio', y='eficiencia_aerobica', trendline="lowess",
                                title="Eficiencia en Carrera (Metros por minuto / Latido) — ¡Hacia arriba es mejor!",
                                color_discrete_sequence=['#deff9a'])
            st.plotly_chart(fig_ef, width='stretch')

        st.divider()

        # --- FILTRO DE PERIODO (ENTRENOS) ---
        st.markdown("### 📅 Filtro de Entrenamientos")
        opcion_periodo = st.radio("Selecciona el periodo a analizar:",
                                  ["Últimos 30 días", "Últimos 3 meses", "Este Año", "Histórico Completo"],
                                  horizontal=True)

        if opcion_periodo == "Últimos 30 días":
            fecha_filtro = fecha_maxima - pd.Timedelta(days=30)
        elif opcion_periodo == "Últimos 3 meses":
            fecha_filtro = fecha_maxima - pd.Timedelta(days=90)
        elif opcion_periodo == "Este Año":
            fecha_filtro = pd.Timestamp(year=fecha_maxima.year, month=1, day=1)
        else:
            fecha_filtro = df_entrenos['fecha_inicio'].min()

        df_filtrado = df_entrenos[df_entrenos['fecha_inicio'] >= fecha_filtro].copy()

        # --- COMPARATIVA INTERANUAL ---
        inicio_pasado = fecha_filtro - pd.Timedelta(days=365)
        fin_pasado = fecha_maxima - pd.Timedelta(days=365)
        df_pasado = df_entrenos[(df_entrenos['fecha_inicio'] >= inicio_pasado) & (df_entrenos['fecha_inicio'] <= fin_pasado)]

        dist_actual    = df_filtrado['distancia_km'].sum()
        tiempo_actual_h = df_filtrado['duracion_min'].sum() / 60
        sesiones_actual = len(df_filtrado)
        dist_pasada    = df_pasado['distancia_km'].sum() if not df_pasado.empty else 0
        tiempo_pasado_h = (df_pasado['duracion_min'].sum() / 60) if not df_pasado.empty else 0
        sesiones_pasada = len(df_pasado) if not df_pasado.empty else 0

        st.markdown(f"### 📊 Resumen del Periodo vs Año Pasado")
        c1, c2, c3 = st.columns(3)
        c1.metric("Sesiones", sesiones_actual, f"{sesiones_actual - sesiones_pasada} vs año pasado")
        c2.metric("Distancia Acumulada", f"{dist_actual:.1f} km", f"{dist_actual - dist_pasada:.1f} km")
        c3.metric("Tiempo de Entreno", f"{tiempo_actual_h:.1f} h", f"{tiempo_actual_h - tiempo_pasado_h:.1f} h")

        st.divider()

        # --- DISTRIBUCIÓN POR DEPORTE + VOLUMEN SEMANAL ---
        col_donut, col_semanal = st.columns([1, 2])

        with col_donut:
            st.markdown("#### 🏅 Distribución por Deporte")
            _ICONOS = {'running': '🏃', 'cycling': '🚴', 'swimming': '🏊',
                       'hiking': '🥾', 'strength_training': '💪', 'yoga': '🧘',
                       'trail_running': '🏔️', 'walking': '🚶'}
            sport_tiempo = df_filtrado.groupby('deporte')['duracion_min'].sum().reset_index()
            sport_tiempo['label'] = sport_tiempo['deporte'].apply(
                lambda d: f"{_ICONOS.get(d.lower(), '🏆')} {d.replace('_', ' ').title()}"
            )
            fig_donut = go.Figure(go.Pie(
                labels=sport_tiempo['label'], values=sport_tiempo['duracion_min'],
                hole=0.55, textinfo='label+percent',
                marker=dict(colors=px.colors.qualitative.Plotly)
            ))
            fig_donut.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_donut, width='stretch')

        with col_semanal:
            st.markdown("#### 📆 Volumen Semanal por Deporte")
            df_semanal = df_filtrado.copy()
            df_semanal['semana'] = df_semanal['fecha_inicio'].dt.to_period('W').apply(lambda r: r.start_time)
            vol_sem = df_semanal.groupby(['semana', 'deporte'])['duracion_min'].sum().unstack(fill_value=0)
            if not vol_sem.empty:
                fig_vol = go.Figure()
                for deporte_col in vol_sem.columns:
                    icono = _ICONOS.get(deporte_col.lower(), '🏆')
                    fig_vol.add_trace(go.Bar(
                        x=vol_sem.index, y=vol_sem[deporte_col] / 60,
                        name=f"{icono} {deporte_col.replace('_', ' ').title()}"
                    ))
                fig_vol.update_layout(barmode='stack', yaxis_title="Horas",
                                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                                      margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_vol, width='stretch')

        st.divider()

        # --- DETALLE DE SESIONES: TARJETAS VISUALES ---
        st.markdown(f"### 📝 Detalle de Sesiones ({opcion_periodo})")
        df_filtrado = df_filtrado.sort_values('fecha_inicio', ascending=False)

        _COLORES_DEPORTE = {
            'running': '#00CC96', 'cycling': '#636EFA', 'swimming': '#19D3F3',
            'hiking': '#FFA15A', 'strength_training': '#EF553B',
            'yoga': '#AB63FA', 'trail_running': '#FF7F0E', 'walking': '#B6B6B6',
        }
        max_trimp = df_filtrado['carga_entreno'].max() if not df_filtrado.empty else 1

        for _, entreno in df_filtrado.iterrows():
            deporte_raw  = str(entreno.get('deporte', 'otro')).lower()
            deporte_label = deporte_raw.replace('_', ' ').title()
            icono        = _ICONOS.get(deporte_raw, '🏆')
            color        = _COLORES_DEPORTE.get(deporte_raw, '#888888')
            distancia    = float(entreno.get('distancia_km', 0) or 0)
            duracion     = float(entreno.get('duracion_min', 0) or 0)
            carga        = float(entreno.get('carga_entreno', 0) or 0)
            fc_media_e   = int(entreno.get('fc_media', 0) or 0)
            fc_max_e     = int(entreno.get('fc_max', 0) or 0)
            ritmo        = str(entreno.get('ritmo', ''))
            desnivel     = str(entreno.get('desnivel_positivo', ''))
            calorias_e   = int(entreno.get('calorias_kcal', 0) or 0)
            ef_e         = float(entreno.get('eficiencia_aerobica', 0) or 0)
            fecha_str    = entreno['fecha_inicio'].strftime('%d %b %Y') if pd.notnull(entreno['fecha_inicio']) else ""
            intensidad   = min(carga / max_trimp, 1.0) if max_trimp > 0 else 0

            with st.container(border=True):
                col_ico, col_info, col_stats = st.columns([0.07, 0.45, 0.48])

                with col_ico:
                    st.markdown(
                        f"<div style='font-size:2.2rem; text-align:center; padding-top:6px'>{icono}</div>",
                        unsafe_allow_html=True
                    )

                with col_info:
                    st.markdown(
                        f"**{fecha_str}** &nbsp;·&nbsp; "
                        f"<span style='color:{color}; font-weight:700'>{deporte_label}</span>",
                        unsafe_allow_html=True
                    )
                    partes = []
                    if distancia > 0: partes.append(f"📍 **{distancia:.2f} km**")
                    if duracion > 0:  partes.append(f"⏱ **{int(duracion)} min**")
                    if ritmo and ritmo not in ('', '0:00', '-'): partes.append(f"🏁 **{ritmo}/km**")
                    if desnivel and desnivel not in ('', '0 m', '0m'): partes.append(f"⛰️ {desnivel}")
                    if partes:
                        st.markdown(" &nbsp;·&nbsp; ".join(partes), unsafe_allow_html=True)
                    if carga > 0:
                        st.caption(f"Carga TRIMP: {carga:.0f} pts")
                        st.progress(intensidad)

                with col_stats:
                    s1, s2, s3, s4 = st.columns(4)
                    if fc_media_e > 0: s1.metric("❤️ FC med", f"{fc_media_e}")
                    if fc_max_e > 0:   s2.metric("🔺 FC máx", f"{fc_max_e}")
                    if calorias_e > 0: s3.metric("🔥 Kcal", f"{calorias_e}")
                    if ef_e > 0:       s4.metric("⚡ Ef.", f"{ef_e:.2f}")
else:
    st.info("⚠️ Aún no se ha sincronizado el archivo de histórico de entrenamientos.")
    
# ==========================================
# SECCIÓN 3: ENTRENADOR VIRTUAL IA (GEMINI)
# ==========================================
st.divider()
st.header("🤖 AI Coach: Análisis Integral")
st.markdown("Gemini cruzará tus datos y generará dos informes detallados: uno clínico (Salud) y uno deportivo (Rendimiento).")

if st.button("✨ Generar Análisis Completo de mi Estado"):
    with st.spinner("Analizando biomarcadores y carga de entrenamiento..."):
        try:
            from google import genai
            
            client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
            
            p_pasos = f"{media_pasos:,.0f}" if 'media_pasos' in locals() else "Sin datos"
            p_hrv = f"{hrv_medio:.0f} ms" if 'hrv_medio' in locals() else "Sin datos"
            p_sueno = f"{sueno_medio:.1f} h" if 'sueno_medio' in locals() else "Sin datos"
            p_fc = f"{fc_media_global:.0f} lpm" if 'fc_media_global' in locals() else "Sin datos"
            
            p_atl = f"{atl_actual:.0f}" if 'atl_actual' in locals() else "0"
            p_ctl = f"{ctl_actual:.0f}" if 'ctl_actual' in locals() else "0"
            p_ratio = f"{ratio_carga:.2f}" if 'ratio_carga' in locals() else "0"

            prompt = f"""
            Actúa como un médico deportivo y entrenador personal de élite.
            Analiza mis métricas de los últimos 30 días y redacta DOS informes separados pero que se entiendan entre sí.

            DATOS DE SALUD (Promedios diarios):
            - Pasos diarios: {p_pasos}
            - Variabilidad Cardíaca (HRV): {p_hrv}
            - Horas de Sueño: {p_sueno}
            - FC Media: {p_fc}

            DATOS DE ENTRENAMIENTO (Modelo TSB):
            - Carga Aguda (Fatiga actual - ATL): {p_atl}
            - Carga Crónica (Fitness asimilado - CTL): {p_ctl}
            - Ratio de Riesgo de Lesión (ATL/CTL): {p_ratio} (Nota: >1.2 es sobrecarga, >1.5 es riesgo alto).

            ESTRUCTURA TU RESPUESTA EXACTAMENTE ASÍ:

            ### 🩺 1. Análisis de Salud y Recuperación
            (Analiza mi volumen de sueño, variabilidad cardíaca y actividad diaria. ¿Estoy descansando lo suficiente? ¿Mi sistema nervioso muestra signos de estrés crónico o estoy recuperando bien?).

            ### 🚴‍♂️ 2. Análisis de Entrenamiento y Rendimiento
            (Analiza mi carga actual, fitness asimilado y riesgo de lesión. Cruza esta información obligatoriamente con mi estado de recuperación de la sección anterior para decirme exactamente qué enfoque o intensidad de sesión debo hacer hoy).
            
            Usa un tono motivador, directo y científico.
            """
            
            respuesta = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            
            st.success("✅ Análisis completado con éxito.")
            st.info(respuesta.text)
            
        except Exception as e:
            st.error(f"Error al conectar con la IA: {e}")
            st.markdown("⚠️ Comprueba que has añadido `GEMINI_API_KEY` a los secretos (Secrets) de Streamlit.")